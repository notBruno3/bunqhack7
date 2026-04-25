"""In-memory embedding cache for the user's historical transactions.

Pre-embedded on first risk score (cheap — gemini-embedding-2 is ~$0.20/M
tokens, the seeded history is well under a thousand tokens total). Keyed by
tx_id, scoped to the current visitor's session.

Why in-memory not sqlite-vec: <100 vectors per user, linear scan in numpy is
sub-millisecond, and shipping a native sqlite extension across Windows demo
machines is a portability landmine we don't need.

The cache lives on the per-session object (see session_manager.Session). All
helpers below resolve `current()` and read/write its `embed_cache` dict so
two visitors don't pollute each other's history baseline.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog
from sqlalchemy import select

from .. import session_manager
from ..db import SessionLocal
from ..integrations.gemini_client import EMBED_DIM, embed_text, embed_texts
from ..models import Transaction
from . import risk_embeddings as risk

log = structlog.get_logger()


def _tx_dict(t: Transaction) -> dict[str, Any]:
    """Convert a Transaction row to the dict shape risk_embeddings expects."""
    return {
        "id": t.id,
        "merchant": t.merchant,
        "amount_eur": t.amount_eur,
        "timestamp": t.created_at,
        "category": _infer_category(t.merchant),
    }


# Lightweight merchant -> category map, used both for seeded history and any
# new transaction that comes through. Keep aligned with MERCHANT_QUALIFIERS
# in risk_embeddings.py — they should describe the same world.
_CATEGORY_MAP: dict[str, str] = {
    "Albert Heijn": "groceries",
    "Jumbo": "groceries",
    "Lidl": "groceries",
    "Spotify": "subscription",
    "Spotify AB": "subscription",
    "Netflix": "subscription",
    "Apple": "digital",
    "NS Reizigers": "transport",
    "GVB": "transport",
    "Bol.com": "shopping",
    "KLM": "travel",
    "Booking.com": "travel",
    "Etsy": "shopping",
    "Ticketmaster": "events",
    "Uber": "transport",
    "Stichting Woonbron": "rent",
    "Bunq Payroll BV": "income",
    "FastWire": "wire transfer",
    "Unknown LLP": "wire transfer",
    "QuickCash Transfer": "wire transfer",
    "Crypto Vault Ltd": "crypto",
    "Offshore Holdings": "wire transfer",
}


def _infer_category(merchant: str) -> str:
    return _CATEGORY_MAP.get(merchant, "uncategorized")


async def _embed_tx(tx_dict: dict[str, Any], history_for_descriptor: list[dict]) -> np.ndarray | None:
    """Embed a single tx and return its L2-normalized vector, or None."""
    desc = risk.descriptor_for(tx_dict, history_for_descriptor)
    raw = await embed_text(desc)
    if raw is None:
        return None
    v = np.array(raw, dtype=np.float32)
    n = float(np.linalg.norm(v))
    if n == 0:
        return None
    return v / n


async def initialize() -> None:
    """Eager-embed all transactions in the current session's DB.

    Idempotent per-session. Uses batch embedding so 50+ transactions complete
    in one round-trip instead of fifty.
    """
    sess = session_manager.current()
    async with sess.embed_init_lock:
        if sess.embed_init_done:
            return
        with SessionLocal() as db:
            txs = list(db.scalars(select(Transaction).order_by(Transaction.created_at.asc())))
        if not txs:
            log.info("embedding_cache_init_empty", session_id=sess.id)
            sess.embed_init_done = True
            return

        # Build descriptors with per-tx as-of history (older context only).
        descriptors: list[str] = []
        running: list[dict[str, Any]] = []
        for t in txs:
            d = _tx_dict(t)
            descriptors.append(risk.descriptor_for(d, running))
            running.append(d)

        vecs = await embed_texts(descriptors)
        embedded = 0
        failed = 0
        for t, raw in zip(txs, vecs, strict=True):
            if raw is None:
                failed += 1
                continue
            v = np.array(raw, dtype=np.float32)
            n = float(np.linalg.norm(v))
            if n == 0:
                failed += 1
                continue
            sess.embed_cache[t.id] = v / n
            embedded += 1
        log.info(
            "embedding_cache_init_done",
            session_id=sess.id,
            embedded=embedded,
            failed=failed,
            total=len(txs),
        )
        sess.embed_init_done = True


def history_dicts() -> list[dict[str, Any]]:
    """Return APPROVED transactions as dicts (for descriptor + scoring).

    Filtering by status=APPROVED is intentional: the user's behavioral
    baseline shouldn't include in-flight verifications (PENDING_VERIFICATION)
    or held/frozen txs. Otherwise scoring a flagged transaction would dilute
    its own novelty signal once the row lands in the DB.
    """
    with SessionLocal() as db:
        txs = list(db.scalars(
            select(Transaction)
            .where(Transaction.status == "APPROVED")
            .order_by(Transaction.created_at.asc())
        ))
    return [_tx_dict(t) for t in txs]


def history_vectors(history: list[dict[str, Any]]) -> np.ndarray | None:
    """Return aligned (N, EMBED_DIM) array of cached vectors. None if empty."""
    cache = session_manager.current().embed_cache
    vecs = [cache[h["id"]] for h in history if h["id"] in cache]
    if not vecs:
        return None
    return np.stack(vecs)


def cache_size() -> int:
    sess = session_manager.current_or_none()
    return len(sess.embed_cache) if sess is not None else 0


def reset() -> None:
    """Clear the current session's cache. Called from mock_bunq.reset_all()."""
    sess = session_manager.current()
    sess.embed_cache.clear()
    sess.embed_init_done = False


async def add_transaction(tx_dict: dict[str, Any]) -> None:
    """Embed and cache a single new transaction. Best-effort — errors logged.

    Called after a NO_RISK tx auto-approves, or after a verification completes,
    so the next risk score has the new history baked in.
    """
    history = [d for d in history_dicts() if d["id"] != tx_dict.get("id")]
    v = await _embed_tx(tx_dict, history)
    if v is not None and "id" in tx_dict:
        session_manager.current().embed_cache[tx_dict["id"]] = v

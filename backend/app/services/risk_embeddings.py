"""Behavioral risk scoring via embeddings.

Replaces the amount-threshold rule with a hybrid score over four axes:
  n_emb   — embedding novelty (semantic-descriptor similarity vs user history)
  n_amt   — robust z-score on log-amount
  n_time  — time-of-day novelty (1 - p(hour))
  p_merch — merchant-reputation penalty

Why this shape: text embeddings cluster well on counterparty/category/recurrence,
but tokenize numbers and clock times poorly — so magnitude axes get their own
closed-form scorers. See FUTURE_AI_INTEGRATIONS.md §4.

Cold start: if the user has fewer than 5 historical txs, fall back to the
amount-threshold rule (the embedding distance and MAD denominator are both
unstable on tiny corpora).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import structlog

from ..integrations.gemini_client import embed_text
from ..schemas import Tier
from ..services import merchant_check

log = structlog.get_logger()

# --- merchant qualifiers ----------------------------------------------------
# Short blurbs that turn a merchant string into a semantically rich descriptor.
# Used in the embedding text, so they steer the cluster — keep them factual
# and category-rich. Unknown merchants get a neutral "no public reputation"
# qualifier that pulls them away from known clusters.

MERCHANT_QUALIFIERS: dict[str, str] = {
    "Albert Heijn": "well-known Dutch supermarket chain, groceries category",
    "Jumbo": "well-known Dutch supermarket chain, groceries category",
    "Lidl": "European discount supermarket chain, groceries category",
    "Spotify": "music streaming subscription service",
    "Spotify AB": "music streaming subscription service",
    "Netflix": "video streaming subscription service",
    "Apple": "consumer electronics and digital services",
    "NS Reizigers": "Dutch national rail operator, public transport",
    "GVB": "Amsterdam municipal transport operator, public transport",
    "Bol.com": "Dutch general retail e-commerce, varied goods",
    "KLM": "Dutch flag-carrier airline, travel category",
    "Booking.com": "travel and accommodation booking service",
    "Etsy": "handmade and vintage goods marketplace",
    "Ticketmaster": "event ticketing service",
    "Uber": "ride-hailing and delivery service",
    "Stichting Woonbron": "Dutch housing corporation, recurring rent payment",
    "Bunq Payroll BV": "salary deposit, recurring monthly income",
    "FastWire": "money-transfer service with no public reputation",
    "Unknown LLP": "unverified counterparty with no public reputation, unknown jurisdiction",
    "QuickCash Transfer": "cash-transfer service with no public reputation",
    "Crypto Vault Ltd": "cryptocurrency-related counterparty, high-risk category",
    "Offshore Holdings": "offshore-jurisdiction counterparty, high-risk category",
}


def merchant_qualifier(merchant: str) -> str:
    return MERCHANT_QUALIFIERS.get(
        merchant, "no public reputation, unknown jurisdiction"
    )


# --- categorical bucketers --------------------------------------------------

_AMOUNT_BUCKETS: list[tuple[float, str]] = [
    (20.0, "tiny under 20 EUR"),
    (100.0, "small 20 to 100 EUR"),
    (500.0, "medium 100 to 500 EUR"),
    (2000.0, "large 500 to 2000 EUR"),
    (math.inf, "very large over 2000 EUR"),
]


def amount_bucket(eur: float) -> str:
    a = abs(eur)
    return next(label for cap, label in _AMOUNT_BUCKETS if a < cap)


def hour_class(hour: int) -> str:
    if 9 <= hour <= 18:
        return "business hours"
    if 18 < hour <= 23:
        return "evening"
    return "overnight"


def weekday_class(weekday: int) -> str:
    return "weekend" if weekday >= 5 else "weekday"


def counterparty_kind(merchant: str, amount: float, category: str | None) -> str:
    """Best-effort classification of the transaction's counterparty type.

    Driven off the merchant_qualifier text so the descriptor has a consistent
    label vocabulary the embedding model can cluster on.
    """
    qual = merchant_qualifier(merchant).lower()
    cat = (category or "").lower()
    if "salary" in qual or "income" in cat:
        return "salary deposit"
    if "rent" in qual or "rent" in cat:
        return "recurring rent payment"
    if "subscription" in qual or "subscription" in cat:
        return "recurring subscription payment"
    if "transport" in qual or "transport" in cat:
        return "domestic transport payment"
    if "supermarket" in qual or cat == "groceries":
        return "domestic retail payment"
    if "no public reputation" in qual and abs(amount) > 1000:
        return "international wire transfer"
    if "no public reputation" in qual:
        return "wire transfer to unverified counterparty"
    return "domestic retail payment"


def history_with_counterparty(merchant: str, history: list[dict[str, Any]]) -> str:
    n = sum(1 for h in history if h["merchant"].lower() == merchant.lower())
    if n == 0:
        return "none"
    if n == 1:
        return "first prior"
    if n <= 3:
        return f"occasional with {n} prior payments"
    return f"frequent with {n} prior payments showing recurring pattern"


def history_in_category(category: str | None, history: list[dict[str, Any]]) -> str:
    if not category:
        return "unknown"
    n = sum(1 for h in history if (h.get("category") or "").lower() == category.lower())
    if n == 0:
        return "none"
    if n <= 3:
        return f"occasional with {n} prior"
    return "frequent"


# --- descriptor builder -----------------------------------------------------


def descriptor_for(tx: dict[str, Any], history: list[dict[str, Any]]) -> str:
    """Build the semantic-descriptor sentence for embedding.

    Deterministic pure function — same template at seed time and at scoring
    time, so historical and new vectors live in aligned cluster space.
    """
    timestamp = tx.get("timestamp")
    if isinstance(timestamp, datetime):
        dt = timestamp
    else:
        dt = datetime.fromisoformat(timestamp) if timestamp else datetime.utcnow()

    cat = tx.get("category") or "uncategorized"
    merchant = tx["merchant"]
    return (
        f"{counterparty_kind(merchant, tx['amount_eur'], cat)}: "
        f"{merchant} ({merchant_qualifier(merchant)}). "
        f"Category: {cat}. "
        f"Amount bucket: {amount_bucket(tx['amount_eur'])}. "
        f"Timing: {weekday_class(dt.weekday())}, {hour_class(dt.hour)}. "
        f"User history with this counterparty: "
        f"{history_with_counterparty(merchant, history)}. "
        f"User history in this category: {history_in_category(cat, history)}."
    )


# --- core scoring -----------------------------------------------------------


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _amount_z(amount: float, history: list[dict[str, Any]]) -> float:
    """Robust z-score on log-amount using median + MAD."""
    log_amts = np.log(np.array([abs(h["amount_eur"]) for h in history]) + 1e-6)
    med = float(np.median(log_amts))
    mad = float(np.median(np.abs(log_amts - med))) + 1e-6
    z = (math.log(abs(amount) + 1e-6) - med) / (1.4826 * mad)
    return z


def _amount_novelty(z: float) -> float:
    """sigmoid((|z|-2)/1.5) — |z|<2 ≈ 0, |z|≈4 ≈ 0.79."""
    return 1.0 / (1.0 + math.exp(-(abs(z) - 2.0) / 1.5))


def _time_novelty(hour: int, history: list[dict[str, Any]]) -> float:
    """1 - p(hour) against user's hour-of-day histogram."""
    if not history:
        return 0.0
    hours = [
        (
            h["timestamp"].hour
            if isinstance(h["timestamp"], datetime)
            else datetime.fromisoformat(h["timestamp"]).hour
        )
        for h in history
    ]
    counts = np.bincount(hours, minlength=24).astype(float)
    p = counts[hour] / max(1.0, counts.sum())
    return float(1.0 - p)


def _merchant_penalty(merchant: str, history: list[dict[str, Any]]) -> float:
    seen = {h["merchant"].lower() for h in history}
    m = merchant.lower()
    if m in seen:
        return 0.0
    rep = merchant_check.lookup(merchant)
    if rep == "GOOD":
        return 0.3
    return 0.6  # UNKNOWN or BAD — both treated as suspicious for this signal


def _knn_novelty(v_new: np.ndarray, history_vecs: np.ndarray, k: int = 3) -> float:
    """1 - mean(top-k cos sim). Top-k dampens single-outlier sensitivity."""
    sims = history_vecs @ v_new  # both already L2-normalized
    if sims.size == 0:
        return 0.5  # neutral if no history vectors at all
    top_k = min(k, int(sims.size))
    top_sims = np.partition(sims, -top_k)[-top_k:]
    return float(1.0 - top_sims.mean())


# --- public API -------------------------------------------------------------

# Tunable weights (sum to 1.0). Calibrated against the seed history.
# Reweighted v2 after observing Gemini Embedding 2's high baseline cosine
# similarity (most txs sit at 0.7-0.9 sim against any other tx, so n_emb
# rarely exceeds ~0.2 even for off-distribution inputs). Magnitude axes
# now carry more of the signal.
W_EMB = 0.30
W_AMT = 0.35
W_TIME = 0.10
W_MERCH = 0.25

THRESHOLD_MID = 0.30
THRESHOLD_HIGH = 0.55
AMOUNT_KILLSWITCH = 0.75  # n_amt >= this forces HIGH_RISK regardless of risk


async def score_transaction(
    tx: dict[str, Any],
    history: list[dict[str, Any]],
    history_vecs: np.ndarray | None,
) -> dict[str, Any]:
    """Score a new transaction and return all component scores + descriptor.

    Caller is responsible for cold-start gating (len(history) < 5) — if so,
    pass empty history and we'll return n_emb = n_amt = n_time = 0 plus the
    merchant penalty, which keeps the score amount-driven.

    history items must have keys: merchant, amount_eur, timestamp, category, vec
    history_vecs is an (N, EMB_DIM) np.ndarray of pre-L2-normalized embeddings,
    aligned with `history` order. May be None if embedding the new tx fails.
    """
    descriptor = descriptor_for(tx, history)

    n_emb = 0.0
    if history and history_vecs is not None and history_vecs.size > 0:
        v_raw = await embed_text(descriptor)
        if v_raw is not None:
            v_new = _l2_normalize(np.array(v_raw, dtype=np.float32))
            n_emb = _knn_novelty(v_new, history_vecs)

    if history:
        z = _amount_z(tx["amount_eur"], history)
        n_amt = _amount_novelty(z)
        ts = tx.get("timestamp")
        dt = ts if isinstance(ts, datetime) else (
            datetime.fromisoformat(ts) if ts else datetime.utcnow()
        )
        n_time = _time_novelty(dt.hour, history)
    else:
        z, n_amt, n_time = 0.0, 0.0, 0.0

    p_merch = _merchant_penalty(tx["merchant"], history)

    risk = (
        W_EMB * n_emb
        + W_AMT * n_amt
        + W_TIME * n_time
        + W_MERCH * p_merch
    )

    return {
        "descriptor": descriptor,
        "risk": risk,
        "n_emb": n_emb,
        "n_amt": n_amt,
        "n_time": n_time,
        "p_merch": p_merch,
        "z_amount": z,
    }


def classify_tier(scores: dict[str, Any]) -> Tier:
    if scores["risk"] >= THRESHOLD_HIGH or scores["n_amt"] >= AMOUNT_KILLSWITCH:
        return "HIGH_RISK"
    if scores["risk"] >= THRESHOLD_MID:
        return "MID_RISK"
    return "NO_RISK"

"""Risk classifier — embedding-driven with amount-threshold fallback.

The primary scorer (`classify_async`) embeds the new transaction's semantic
descriptor against the user's history of pre-embedded transactions and
combines it with closed-form magnitude axes (amount z-score, time-of-day
novelty, merchant reputation).

`classify_fallback` is the old amount-threshold rule, used when:
  - the user is in cold start (<5 historical txs, history is unstable)
  - the embedding API is unavailable
  - an explicit `force_tier` is set on the initiate request (tests / manual override)
  - state.force_tier is set (deprecated runtime override)
"""

from __future__ import annotations

from typing import Any

import structlog

from ..schemas import Tier
from ..state import state
from . import embedding_cache, merchant_check, risk_embeddings

log = structlog.get_logger()

MID_THRESHOLD_EUR = 250.0
HIGH_THRESHOLD_EUR = 2000.0
COLD_START_MIN_HISTORY = 5


def classify_fallback(amount_eur: float, merchant: str) -> Tier:
    """Amount-threshold rule. Used only as fallback (cold start, embed errors)."""
    reputation = merchant_check.lookup(merchant)
    if amount_eur >= HIGH_THRESHOLD_EUR or reputation == "BAD":
        if amount_eur >= HIGH_THRESHOLD_EUR:
            return "HIGH_RISK"
        return "MID_RISK"
    if amount_eur >= MID_THRESHOLD_EUR or reputation == "UNKNOWN":
        return "MID_RISK"
    return "NO_RISK"


async def classify_async(
    amount_eur: float,
    merchant: str,
    explicit: Tier | None = None,
) -> tuple[Tier, dict[str, Any] | None]:
    """Return (tier, scores). scores is None for fallback paths."""
    # Explicit per-request override always wins (used for NO_RISK fast-path
    # and for tests).
    if explicit is not None:
        return explicit, None

    # Deprecated runtime override — kept for back-compat with mock_control.
    if state.force_tier is not None:
        tier = state.force_tier
        state.force_tier = None
        return tier, None

    history = embedding_cache.history_dicts()

    # Cold start — fall back to thresholds rather than scoring against
    # an unstable history.
    if len(history) < COLD_START_MIN_HISTORY:
        log.info("risk_cold_start", history_size=len(history))
        return classify_fallback(amount_eur, merchant), None

    # Build the new tx in the dict shape risk_embeddings expects.
    tx = {
        "merchant": merchant,
        "amount_eur": amount_eur,
        "category": embedding_cache._infer_category(merchant),  # private helper, intentional
        "timestamp": None,  # use "now" inside descriptor_for
    }
    history_vecs = embedding_cache.history_vectors(history)
    scores = await risk_embeddings.score_transaction(tx, history, history_vecs)
    tier = risk_embeddings.classify_tier(scores)
    log.info(
        "risk_classified",
        tier=tier,
        risk=round(scores["risk"], 3),
        n_emb=round(scores["n_emb"], 3),
        n_amt=round(scores["n_amt"], 3),
        n_time=round(scores["n_time"], 3),
        p_merch=round(scores["p_merch"], 3),
        merchant=merchant,
        amount_eur=amount_eur,
    )
    return tier, scores


# Back-compat shim: existing callers that don't await still work for the
# explicit / force_tier paths. Embedding-driven classification requires await.
def classify(amount_eur: float, merchant: str, explicit: Tier | None = None) -> Tier:
    if explicit is not None:
        return explicit
    if state.force_tier is not None:
        tier = state.force_tier
        state.force_tier = None
        return tier
    return classify_fallback(amount_eur, merchant)

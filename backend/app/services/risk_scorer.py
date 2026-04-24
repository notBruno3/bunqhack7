"""Rule-based risk classifier.

The scoring rules here are intentionally simple — they're a gate for the
verification flow, not the product. Demo operator can override via
state.force_tier (set by POST /api/mock/force_tier) or via the
`force_tier` field on the initiate request.
"""

from __future__ import annotations

from ..schemas import Tier
from ..state import state
from . import merchant_check

MID_THRESHOLD_EUR = 250.0
HIGH_THRESHOLD_EUR = 2000.0


def classify(amount_eur: float, merchant: str, explicit: Tier | None = None) -> Tier:
    if explicit is not None:
        return explicit
    if state.force_tier is not None:
        tier = state.force_tier
        state.force_tier = None  # one-shot override
        return tier

    reputation = merchant_check.lookup(merchant)

    if amount_eur >= HIGH_THRESHOLD_EUR or reputation == "BAD":
        if amount_eur >= HIGH_THRESHOLD_EUR:
            return "HIGH_RISK"
        return "MID_RISK"
    if amount_eur >= MID_THRESHOLD_EUR or reputation == "UNKNOWN":
        return "MID_RISK"
    return "NO_RISK"

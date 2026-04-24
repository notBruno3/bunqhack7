"""Ephemeral in-process state used to script the live demo.

This is intentionally separate from the persistent DB: the demo operator
pokes these knobs through /api/mock/* and the orchestrator reads them
during a verification. Nothing here survives a restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import Tier

VALID_SCENARIOS = {
    "mid_clean",
    "mid_ambiguous_good_merchant",
    "mid_ambiguous_bad_merchant",
    "mid_flagged",
    "high_pass",
    "high_fail",
}


@dataclass
class DemoState:
    # Tier override consumed by risk_scorer on the NEXT initiate and then cleared.
    force_tier: Tier | None = None
    # Scenario pins the mock AI outputs (Hume / Gemini / Claude) until changed.
    scenario: str | None = None
    # Runtime mock toggle, seeded from settings.mock_mode.
    mock_mode: bool = field(default=True)


state = DemoState()

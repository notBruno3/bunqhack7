"""Per-session demo knobs (force_tier, scenario, mock_mode).

The demo operator pokes these through /api/mock/*. They are NOT shared across
visitors — each browser session has its own DemoState object held on the
session_manager.Session. The `state` symbol exported below is a proxy whose
attribute reads/writes route to `current().demo_state`, so existing call
sites (`state.scenario = "..."`) keep working unchanged.
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


class _DemoStateProxy:
    """Attribute-access proxy to `current().demo_state`.

    Falls back to a module-level default DemoState when no session is bound
    (e.g., during startup logging before any request arrives). This default
    is read-only in practice — callers that mutate run inside a request
    where a real session is bound.
    """

    __slots__ = ()

    def _target(self) -> DemoState:
        # Local import to dodge the import cycle with session_manager.
        from . import session_manager

        sess = session_manager.current_or_none()
        if sess is not None:
            return sess.demo_state
        return _DEFAULT_STATE

    def __getattr__(self, name: str):
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._target(), name, value)


_DEFAULT_STATE = DemoState()
state = _DemoStateProxy()

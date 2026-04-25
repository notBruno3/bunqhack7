"""Demo operator control surface.

These endpoints let the person running the live pitch pin outcomes before
the next transaction. Nothing here talks to the DB state except reset.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas import ForceTierReq, MockToggleReq
from ..services import mock_bunq
from ..state import VALID_SCENARIOS, state

router = APIRouter()


@router.get("/status")
def status() -> dict:
    return {
        "mock_mode": state.mock_mode,
        "scenario": state.scenario,
        "force_tier": state.force_tier,
        "scenarios_available": sorted(VALID_SCENARIOS),
    }


@router.post("/scenario/{name}")
def set_scenario(name: str) -> dict:
    """Set the scenario for mock-fallback hints.

    Phase 3 note: this NO LONGER sets force_tier. The embedding-based risk
    classifier now decides the tier from real signals (amount + merchant +
    user history). Scenario remains useful only as a hint for the mock
    fallback when a provider call fails.
    """
    if name not in VALID_SCENARIOS:
        raise HTTPException(status_code=404, detail=f"unknown_scenario:{name}")
    state.scenario = name
    return {"scenario": state.scenario, "force_tier": state.force_tier}


@router.post("/scenario/clear")
def clear_scenario() -> dict:
    state.scenario = None
    return {"scenario": None}


@router.post("/force_tier")
def force_tier(req: ForceTierReq) -> dict:
    state.force_tier = req.tier
    return {"force_tier": state.force_tier}


@router.post("/toggle")
def toggle(req: MockToggleReq) -> dict:
    state.mock_mode = req.mock
    return {"mock_mode": state.mock_mode}


@router.post("/reset")
async def reset() -> dict:
    from ..services import embedding_cache

    mock_bunq.reset_all()
    state.scenario = None
    state.force_tier = None
    # Re-embed the freshly seeded history so the next initiate isn't cold-start.
    try:
        await embedding_cache.initialize()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "history_embedded": embedding_cache.cache_size()}

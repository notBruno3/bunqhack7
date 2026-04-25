"""Canned provider outputs keyed by the active demo scenario.

The orchestrator reads `state.scenario` to decide which preset to return
when MOCK_MODE is on or when a provider call errors out. The presets
match the decision table in IDEA.md so the final Claude verdict is
predictable on stage.
"""

from __future__ import annotations

from ..schemas import GeminiSummary, HumeScores, Verdict

HUME_CLEAN = HumeScores(
    calmness=0.82, fear=0.05, distress=0.04, anxiety=0.08,
    confidence_overall=0.9, verdict_hint="CLEAN",
    note="Calm prosody, steady pacing, no distress markers.",
)
HUME_AMBIGUOUS = HumeScores(
    calmness=0.45, fear=0.28, distress=0.22, anxiety=0.40,
    confidence_overall=0.5, verdict_hint="AMBIGUOUS",
    note="Mixed signals — elevated anxiety but no clear distress.",
)
HUME_FLAGGED = HumeScores(
    calmness=0.12, fear=0.72, distress=0.66, anxiety=0.80,
    confidence_overall=0.88, verdict_hint="FLAGGED",
    note="Distress markers: shaky voice, rapid pacing, elevated fear.",
)

GEMINI_HOME_SAFE = GeminiSummary(
    location_type="home_indoor",
    duress_signals=[],
    confidence=0.9,
    raw_text="Well-lit indoor home environment. User alone, relaxed posture.",
)
GEMINI_DURESS = GeminiSummary(
    location_type="public_unfamiliar",
    duress_signals=["second_person_visible", "user_glances_offscreen", "low_light"],
    confidence=0.85,
    raw_text="Dimly-lit unfamiliar setting. A second person is partially visible; user repeatedly glances offscreen.",
)

_PRESETS: dict[str, dict] = {
    "mid_clean": {
        "hume": HUME_CLEAN,
        "gemini": None,
        "verdict": Verdict(
            verdict="APPROVED",
            confidence=0.9,
            rationale="Calm prosody and reputable merchant — intent verified.",
            recommended_action="Proceed with transaction.",
        ),
    },
    "mid_ambiguous_good_merchant": {
        "hume": HUME_AMBIGUOUS,
        "gemini": None,
        "verdict": Verdict(
            verdict="APPROVED",
            confidence=0.7,
            rationale="Mixed voice signals but merchant reputation is GOOD; proceed.",
            recommended_action="Proceed; retain audit trail.",
        ),
    },
    "mid_ambiguous_bad_merchant": {
        "hume": HUME_AMBIGUOUS,
        "gemini": None,
        "verdict": Verdict(
            verdict="HELD_FOR_REVIEW",
            confidence=0.75,
            rationale="Ambiguous prosody combined with suspicious merchant — escalate.",
            recommended_action="Open compliance ticket; contact user on backup channel.",
        ),
    },
    "mid_flagged": {
        "hume": HUME_FLAGGED,
        "gemini": None,
        "verdict": Verdict(
            verdict="HELD_FOR_REVIEW",
            confidence=0.88,
            rationale="Clear distress markers in voice — coercion signature.",
            recommended_action="Hold transaction; compliance contacts user on backup channel.",
        ),
    },
    "high_pass": {
        "hume": HUME_CLEAN,
        "gemini": GEMINI_HOME_SAFE,
        "verdict": Verdict(
            verdict="APPROVED",
            confidence=0.93,
            rationale="Calm voice, safe familiar environment, no duress signals.",
            recommended_action="Proceed; retain full audio/video audit trail for PSD3.",
        ),
    },
    "high_fail": {
        "hume": HUME_FLAGGED,
        "gemini": GEMINI_DURESS,
        "verdict": Verdict(
            verdict="FROZEN",
            confidence=0.95,
            rationale="Distress voice plus unfamiliar environment with a second person visible — likely coerced.",
            recommended_action="Freeze transaction; escalate to Bunq compliance immediately.",
        ),
    },
}


def hume_for(scenario: str | None) -> HumeScores:
    if scenario and scenario in _PRESETS:
        return _PRESETS[scenario]["hume"]
    return HUME_CLEAN


def gemini_for(scenario: str | None) -> GeminiSummary:
    if scenario and scenario in _PRESETS and _PRESETS[scenario]["gemini"] is not None:
        return _PRESETS[scenario]["gemini"]
    return GEMINI_HOME_SAFE


def verdict_for(scenario: str | None) -> Verdict | None:
    if scenario and scenario in _PRESETS:
        return _PRESETS[scenario]["verdict"]
    return None


def fallback_verdict(hume: HumeScores | None, gemini: GeminiSummary | None) -> Verdict:
    """Used when Claude is unavailable — a simple rule over signals."""
    hint = hume.verdict_hint if hume else "AMBIGUOUS"
    duress = bool(gemini and gemini.duress_signals)
    if hint == "FLAGGED" or duress:
        return Verdict(
            verdict="HELD_FOR_REVIEW",
            confidence=0.6,
            rationale="Fallback rule: distress signals detected (Claude unavailable).",
            recommended_action="Escalate to human compliance review.",
        )
    if hint == "AMBIGUOUS":
        return Verdict(
            verdict="HELD_FOR_REVIEW",
            confidence=0.5,
            rationale="Fallback rule: ambiguous emotional signals (Claude unavailable).",
            recommended_action="Run merchant check; if suspicious, escalate.",
        )
    return Verdict(
        verdict="APPROVED",
        confidence=0.7,
        rationale="Fallback rule: clean signals, no duress (Claude unavailable).",
        recommended_action="Proceed with transaction.",
    )

"""Claude orchestration — merge signals into a structured Verdict.

Uses the Anthropic SDK's tool use to force a JSON response that matches
the Verdict schema exactly. The system prompt is stable across every
verification so we mark it cache_control=ephemeral to cut cost/latency.
"""

from __future__ import annotations

import json

import structlog

from ..config import settings
from ..schemas import GeminiSummary, HumeScores, MerchantReputation, Tier, Verdict
from ..state import state
from . import mocks

log = structlog.get_logger()

SYSTEM_PROMPT = """You are the final decision node in a bank's transaction intent-verification pipeline.

You receive:
- tier: NO_RISK, MID_RISK, or HIGH_RISK
- hume_scores: live voice prosody (calmness, fear, distress, anxiety, verdict_hint)
- gemini_summary: video analysis of the user's environment (for HIGH_RISK)
- merchant_reputation: GOOD, BAD, or UNKNOWN
- transaction: amount, merchant, user_id

Decision rubric:
- MID_RISK + Hume CLEAN → APPROVED
- MID_RISK + Hume AMBIGUOUS + merchant GOOD → APPROVED
- MID_RISK + Hume AMBIGUOUS + merchant BAD/UNKNOWN → HELD_FOR_REVIEW
- MID_RISK + Hume FLAGGED → HELD_FOR_REVIEW
- HIGH_RISK + Hume CLEAN + no duress signals → APPROVED
- HIGH_RISK + any duress signal OR Hume FLAGGED → FROZEN
- HIGH_RISK + Hume AMBIGUOUS + no duress → HELD_FOR_REVIEW

If a provider is unavailable (service_available=false), be CONSERVATIVE:
- HIGH_RISK with any missing signal → HELD_FOR_REVIEW minimum
- Never APPROVED on a HIGH_RISK with missing signals

You MUST call the return_verdict tool. Do not respond with prose."""


VERDICT_TOOL = {
    "name": "return_verdict",
    "description": "Return the final verification verdict as structured JSON.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["APPROVED", "HELD_FOR_REVIEW", "FROZEN"]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "rationale": {"type": "string", "description": "1-2 sentences explaining the decision."},
            "recommended_action": {"type": "string", "description": "Concrete next step."},
        },
        "required": ["verdict", "confidence", "rationale", "recommended_action"],
    },
}


async def decide(
    tier: Tier,
    hume: HumeScores | None,
    gemini: GeminiSummary | None,
    merchant_reputation: MerchantReputation,
    amount_eur: float,
    merchant: str,
    user_id: str,
) -> Verdict:
    if state.mock_mode or not settings.anthropic_api_key:
        scripted = mocks.verdict_for(state.scenario)
        return scripted if scripted else mocks.fallback_verdict(hume, gemini)

    try:
        return await _decide_real(tier, hume, gemini, merchant_reputation, amount_eur, merchant, user_id)
    except Exception as e:  # noqa: BLE001
        log.warning("claude_failed", error=str(e))
        return mocks.fallback_verdict(hume, gemini)


async def _decide_real(
    tier: Tier,
    hume: HumeScores | None,
    gemini: GeminiSummary | None,
    merchant_reputation: MerchantReputation,
    amount_eur: float,
    merchant: str,
    user_id: str,
) -> Verdict:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_payload = {
        "tier": tier,
        "hume_scores": hume.model_dump() if hume else None,
        "gemini_summary": gemini.model_dump() if gemini else None,
        "merchant_reputation": merchant_reputation,
        "transaction": {"amount_eur": amount_eur, "merchant": merchant, "user_id": user_id},
    }

    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[VERDICT_TOOL],
        tool_choice={"type": "tool", "name": "return_verdict"},
        messages=[{"role": "user", "content": json.dumps(user_payload)}],
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "return_verdict":
            return Verdict.model_validate(block.input)

    raise RuntimeError("Claude did not return a tool_use block")

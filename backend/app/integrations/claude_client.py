"""Claude orchestration — question generation + final verdict.

Uses the Anthropic SDK's tool use to force structured JSON responses. System
prompts are stable across verifications so we mark them cache_control=ephemeral
to amortize cost across requests.

Two tool calls per HIGH/MID_RISK verification:
  1. generate_questions(tx_context) -> 3-5 questions
  2. return_verdict(per_q_buckets, gemini_summary) -> APPROVED | HELD | FROZEN
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
- tier: MID_RISK or HIGH_RISK (NO_RISK never reaches you)
- questions: a list of questions the user was asked, each with:
  - text, purpose (baseline | intent | context | knowledge_check | stress_probe)
  - transcript: what the user said (best-effort STT, may be empty if no STT was run)
  - hume_scores: per-question prosody (calmness, fear, distress, anxiety, verdict_hint)
  - is_baseline (true for Q1 — used to compute deltas)
  - delta_vs_baseline (for non-baseline Qs: how much fear/distress/anxiety increased)
- gemini_summary: video analysis of the user's environment (for HIGH_RISK)
- merchant_reputation: GOOD, BAD, or UNKNOWN
- risk_signals: embedding-based behavioral score components (n_emb, n_amt, n_time, p_merch, risk)
- transaction: amount, merchant, user_id

Decision principles (reason about DELTAS from baseline, not absolute Hume values):
- MID_RISK: any answer with delta(distress) > 0.3 OR delta(fear) > 0.4 → HELD_FOR_REVIEW.
- MID_RISK with calm voice across all questions → APPROVED.
- MID_RISK with mixed signals + BAD/UNKNOWN merchant → HELD_FOR_REVIEW.
- HIGH_RISK with ANY duress signal in gemini_summary AND confidence > 0.5 → FROZEN.
- HIGH_RISK with calm voice + safe environment → APPROVED, but only if all signals are present.
- HIGH_RISK with any provider service_available=false → HELD_FOR_REVIEW minimum (never APPROVED).
- HIGH_RISK with the embedding score n_amt >= 0.9 AND distress signals → FROZEN.

Knowledge_check incoherence (the user gave an unrelated or vague answer to a specific question)
is also a strong signal — if a knowledge_check Q's transcript is incoherent or evasive,
escalate by one tier.

You MUST call the return_verdict tool. Do not respond with prose."""


GENERATE_QUESTIONS_SYSTEM = """You are the verification-question planner for a bank's intent-verification system.
A transaction has been flagged for voice (and optionally video) verification.

You must generate 3-5 questions to ask the user. The questions are spoken by a TTS
system; the user's voice answers are scored for emotional state by Hume. Your goal:
design questions that distinguish a calm, willing user from a coerced or scammed one.

Rules:
- The FIRST question MUST be benign and identity-confirming, used to baseline the
  user's voice. Examples: "Please confirm your first name." or "Could you say today's date?"
- Subsequent questions probe in three ways:
  - intent — "What is this payment for?"
  - context — "Who is the recipient and how did you find them?"
  - knowledge_check — small details only the rightful payer would know
    ("Is this part of a larger plan, or a one-off?")
- For HIGH_RISK transactions, include exactly ONE stress_probe — designed to surface
  tension if the user is being coerced or scammed
  ("Is anyone with you right now who suggested this transaction?").
  Do NOT include a stress_probe for MID_RISK.
- Questions must be conversational, under 18 words each, answerable in 1-2 sentences.
- Tailor to the transaction. If the merchant is unfamiliar or the amount unusual,
  ask about it. Do NOT volunteer the bank's suspicion ("we noticed this is unusual") —
  keep questions neutral.
- Generate exactly 3 questions for MID_RISK, exactly 4 for HIGH_RISK.

You MUST call the generate_questions tool. Do not respond with prose."""


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


GENERATE_QUESTIONS_TOOL = {
    "name": "generate_questions",
    "description": "Generate 3-5 verification questions tailored to a flagged transaction.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 3,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "stable id like q1, q2, q3"},
                        "text": {"type": "string", "description": "question to speak to the user, under 18 words"},
                        "purpose": {
                            "type": "string",
                            "enum": ["baseline", "intent", "context", "knowledge_check", "stress_probe"],
                        },
                        "expected_answer_shape": {
                            "type": "string",
                            "description": "One short clause describing what a coherent answer looks like.",
                        },
                    },
                    "required": ["id", "text", "purpose", "expected_answer_shape"],
                },
            }
        },
        "required": ["questions"],
    },
}


# --- generate_questions ----------------------------------------------------


_FALLBACK_QUESTIONS_MID = [
    {"id": "q1", "text": "Please confirm your first name out loud.", "purpose": "baseline",
     "expected_answer_shape": "the user's first name"},
    {"id": "q2", "text": "What is this payment for?", "purpose": "intent",
     "expected_answer_shape": "a brief description of the purpose"},
    {"id": "q3", "text": "How do you know the recipient?", "purpose": "context",
     "expected_answer_shape": "a relationship or how they found them"},
]
_FALLBACK_QUESTIONS_HIGH = _FALLBACK_QUESTIONS_MID + [
    {"id": "q4", "text": "Is anyone with you who asked you to make this payment?", "purpose": "stress_probe",
     "expected_answer_shape": "yes or no with brief context"},
]


async def generate_questions(
    tier: Tier,
    amount_eur: float,
    merchant: str,
    merchant_reputation: MerchantReputation,
    risk_signals: dict | None = None,
    user_history_summary: str = "",
) -> list[dict]:
    """Generate verification questions. Always returns at least the fallback set."""
    if state.mock_mode or not settings.anthropic_api_key:
        return list(_FALLBACK_QUESTIONS_HIGH if tier == "HIGH_RISK" else _FALLBACK_QUESTIONS_MID)
    try:
        return await _generate_questions_real(
            tier, amount_eur, merchant, merchant_reputation, risk_signals, user_history_summary
        )
    except Exception as e:  # noqa: BLE001
        log.warning("question_gen_failed", error=str(e))
        return list(_FALLBACK_QUESTIONS_HIGH if tier == "HIGH_RISK" else _FALLBACK_QUESTIONS_MID)


async def _generate_questions_real(
    tier: Tier,
    amount_eur: float,
    merchant: str,
    merchant_reputation: MerchantReputation,
    risk_signals: dict | None,
    user_history_summary: str,
) -> list[dict]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_payload = {
        "tier": tier,
        "transaction": {"amount_eur": amount_eur, "merchant": merchant, "merchant_reputation": merchant_reputation},
        "risk_signals": risk_signals,
        "user_history_summary": user_history_summary,
    }
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": GENERATE_QUESTIONS_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[GENERATE_QUESTIONS_TOOL],
        tool_choice={"type": "tool", "name": "generate_questions"},
        messages=[{"role": "user", "content": json.dumps(user_payload)}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "generate_questions":
            qs = list(block.input.get("questions") or [])
            if qs:
                return qs
    raise RuntimeError("Claude did not return generate_questions tool_use")


async def decide(
    tier: Tier,
    hume: HumeScores | None,
    gemini: GeminiSummary | None,
    merchant_reputation: MerchantReputation,
    amount_eur: float,
    merchant: str,
    user_id: str,
    questions: list[dict] | None = None,
    risk_signals: dict | None = None,
) -> Verdict:
    """Final verification verdict.

    Phase 2 onward: pass per-question buckets via `questions`. Each item:
      {id, text, purpose, transcript, hume_scores, is_baseline, delta_vs_baseline}
    The single `hume` arg remains supported as a fallback (aggregated bucket).
    """
    if state.mock_mode or not settings.anthropic_api_key:
        scripted = mocks.verdict_for(state.scenario)
        return scripted if scripted else mocks.fallback_verdict(hume, gemini)

    try:
        return await _decide_real(
            tier, hume, gemini, merchant_reputation, amount_eur, merchant, user_id,
            questions=questions, risk_signals=risk_signals,
        )
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
    questions: list[dict] | None = None,
    risk_signals: dict | None = None,
) -> Verdict:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_payload = {
        "tier": tier,
        "questions": questions or [],
        "hume_scores": hume.model_dump() if hume else None,
        "gemini_summary": gemini.model_dump() if gemini else None,
        "merchant_reputation": merchant_reputation,
        "risk_signals": risk_signals,
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

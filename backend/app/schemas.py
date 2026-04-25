from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Tier = Literal["NO_RISK", "MID_RISK", "HIGH_RISK"]
TransactionStatus = Literal[
    "APPROVED",
    "PENDING_VERIFICATION",
    "HELD_FOR_REVIEW",
    "FROZEN",
    "REJECTED",
]
VerdictKind = Literal["APPROVED", "HELD_FOR_REVIEW", "FROZEN"]
MerchantReputation = Literal["GOOD", "BAD", "UNKNOWN"]


class TransactionInitiateReq(BaseModel):
    amount_eur: float = Field(gt=0)
    merchant: str
    user_id: str = "demo-user-1"
    force_tier: Tier | None = None


class TransactionInitiateRes(BaseModel):
    transaction_id: str
    tier: Tier
    status: TransactionStatus
    verification_id: str | None = None
    ws_url: str | None = None
    merchant_reputation: MerchantReputation


class HumeScores(BaseModel):
    calmness: float = 0.0
    fear: float = 0.0
    distress: float = 0.0
    anxiety: float = 0.0
    confidence_overall: float = 0.0
    verdict_hint: Literal["CLEAN", "AMBIGUOUS", "FLAGGED"] = "CLEAN"
    service_available: bool = True
    note: str = ""


class GeminiSummary(BaseModel):
    location_type: str = "unknown"
    duress_signals: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw_text: str = ""
    service_available: bool = True


class Verdict(BaseModel):
    verdict: VerdictKind
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    recommended_action: str


# WebSocket envelopes. Clients should tag messages with `type`.
class WsClientStart(BaseModel):
    type: Literal["start"] = "start"


class WsClientAudioChunk(BaseModel):
    type: Literal["audio_chunk"] = "audio_chunk"
    data: str  # base64 pcm16 16kHz mono
    q_id: str | None = None  # which question this chunk is for (Phase 2+)


class WsClientAnswerEnd(BaseModel):
    """Phase 2: client signals it has finished sending audio for a given question."""

    type: Literal["answer_end"] = "answer_end"
    q_id: str
    transcript: str = ""  # browser-side STT, optional


class WsClientVideoFrame(BaseModel):
    type: Literal["video_frame"] = "video_frame"
    data: str  # base64 jpeg


class WsClientGemini(BaseModel):
    """Phase 2: client forwards its frontend-computed Gemini summary."""

    type: Literal["client_gemini"] = "client_gemini"
    summary: dict


class WsClientEnd(BaseModel):
    type: Literal["end"] = "end"


class WsServerReady(BaseModel):
    type: Literal["ready"] = "ready"
    tier: Tier
    questions: list[dict] = Field(default_factory=list)


class WsServerHumePartial(BaseModel):
    type: Literal["hume_partial"] = "hume_partial"
    scores: HumeScores
    q_id: str | None = None  # which question this score belongs to (Phase 2+)
    delta_vs_baseline: dict[str, float] | None = None


class WsServerGeminiPartial(BaseModel):
    type: Literal["gemini_partial"] = "gemini_partial"
    summary: GeminiSummary


class WsServerDecision(BaseModel):
    type: Literal["decision"] = "decision"
    verdict: VerdictKind
    rationale: str
    audit_log_id: str


class WsServerError(BaseModel):
    type: Literal["error"] = "error"
    reason: str


class QuestionAnswer(BaseModel):
    """One question + the user's answer + the Hume bucket for that answer."""

    id: str
    text: str
    purpose: Literal["baseline", "intent", "context", "knowledge_check", "stress_probe"]
    transcript: str = ""
    hume_scores: HumeScores | None = None
    is_baseline: bool = False
    delta_vs_baseline: dict[str, float] | None = None


class AuditLogOut(BaseModel):
    id: str
    verification_id: str | None = None
    transaction_id: str
    tier: Tier
    hume_scores: HumeScores | None = None
    gemini_summary: GeminiSummary | None = None
    merchant_reputation: MerchantReputation
    verdict: Verdict
    risk_signals: dict | None = None
    questions: list[QuestionAnswer] | None = None
    started_at: datetime
    decided_at: datetime
    duration_ms: int


class TicketOut(BaseModel):
    id: str
    transaction_id: str
    verification_id: str
    status: Literal["OPEN", "APPROVED", "REJECTED"]
    tier: Tier
    amount_eur: float
    merchant: str
    user_id: str
    created_at: datetime
    audit_log: AuditLogOut


class TicketDecisionReq(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = None


class ForceTierReq(BaseModel):
    tier: Tier | None = None  # null clears the override


class MockToggleReq(BaseModel):
    mock: bool

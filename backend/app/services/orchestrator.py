"""Verification orchestrator — runs Hume + Gemini + Claude and persists audit.

Called from the /ws/verify route once the client has finished sending
audio (and video, for HIGH_RISK). Providers run in parallel via
asyncio.gather; any failure is absorbed into a service_available=false
signal so Claude still gets to decide something.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import structlog
from sqlalchemy.orm import Session

from ..integrations import claude_client, gemini_client, hume_client
from ..models import AuditLog, Ticket, Transaction, Verification
from ..schemas import GeminiSummary, HumeScores, Verdict
from ..util import new_id

log = structlog.get_logger()


async def run_verification(
    db: Session,
    verification: Verification,
    transaction: Transaction,
    pcm_audio: bytes,
    jpeg_frames: list[bytes],
) -> tuple[Verdict, AuditLog, HumeScores | None, GeminiSummary | None]:
    started_at = datetime.utcnow()
    tier = transaction.tier

    hume_task: asyncio.Task[HumeScores] = asyncio.create_task(hume_client.score_audio(pcm_audio))
    gemini_task: asyncio.Task[GeminiSummary] | None = None
    if tier == "HIGH_RISK":
        gemini_task = asyncio.create_task(gemini_client.analyze_av(jpeg_frames, pcm_audio))

    results = await asyncio.gather(
        hume_task,
        gemini_task if gemini_task else _noop(),
        return_exceptions=True,
    )

    hume_scores = results[0] if not isinstance(results[0], BaseException) else None
    gemini_summary = (
        results[1] if gemini_task and not isinstance(results[1], BaseException) else None
    )

    verdict = await claude_client.decide(
        tier=tier,  # type: ignore[arg-type]
        hume=hume_scores,
        gemini=gemini_summary,
        merchant_reputation=transaction.merchant_reputation,  # type: ignore[arg-type]
        amount_eur=transaction.amount_eur,
        merchant=transaction.merchant,
        user_id=transaction.user_id,
    )

    decided_at = datetime.utcnow()
    duration_ms = int((decided_at - started_at).total_seconds() * 1000)

    audit = AuditLog(
        id=new_id("aud"),
        verification_id=verification.id,
        transaction_id=transaction.id,
        tier=tier,
        hume_scores=hume_scores.model_dump() if hume_scores else None,
        gemini_summary=gemini_summary.model_dump() if gemini_summary else None,
        merchant_reputation=transaction.merchant_reputation,
        verdict=verdict.model_dump(),
        risk_signals=getattr(verification, "risk_signals", None),
        questions=getattr(verification, "questions", None),
        started_at=started_at,
        decided_at=decided_at,
        duration_ms=duration_ms,
    )
    db.add(audit)

    status_map = {"APPROVED": "APPROVED", "HELD_FOR_REVIEW": "HELD_FOR_REVIEW", "FROZEN": "FROZEN"}
    transaction.status = status_map[verdict.verdict]
    verification.status = "COMPLETE"

    if verdict.verdict in {"HELD_FOR_REVIEW", "FROZEN"}:
        db.add(
            Ticket(
                id=new_id("tkt"),
                transaction_id=transaction.id,
                verification_id=verification.id,
                audit_log_id=audit.id,
                status="OPEN",
            )
        )

    db.commit()
    log.info(
        "verification_done",
        verification_id=verification.id,
        tier=tier,
        verdict=verdict.verdict,
        duration_ms=duration_ms,
        hume_ok=hume_scores is not None,
        gemini_ok=gemini_summary is not None or tier != "HIGH_RISK",
    )
    return verdict, audit, hume_scores, gemini_summary


async def _noop() -> None:
    return None

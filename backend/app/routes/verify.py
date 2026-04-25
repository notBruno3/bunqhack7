"""WebSocket verification endpoint — Phase 2 per-question protocol.

Handshake (server -> client):
  {"type": "ready", "tier": "...", "questions": [{id, text, purpose, expected_answer_shape}]}

Per-question loop (repeat for each question):
  client -> server: {"type": "audio_chunk", "q_id": "q1", "data": "<base64 pcm16>"}
  ...                                   (multiple chunks)
  client -> server: {"type": "answer_end", "q_id": "q1", "transcript": "optional"}
  server -> client: {"type": "hume_partial", "q_id": "q1",
                     "scores": {...}, "delta_vs_baseline": {...}}

HIGH_RISK only (concurrent):
  client -> server: {"type": "video_frame", "data": "<base64 jpeg>"}
  client -> server: {"type": "client_gemini", "summary": {...}}
  server -> client: {"type": "gemini_partial", "summary": {...}}     (echo)

Termination:
  client -> server: {"type": "end"}
  server -> client: {"type": "decision", ...}

Backward compatibility: if the client sends `audio_chunk` without `q_id`, the
server falls into the legacy path — buffer all audio, run one Hume call, run
one Claude.decide call. The existing mock-mode smoke test depends on this.
"""

from __future__ import annotations

import asyncio
import base64

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from .. import session_manager
from ..db import SessionLocal
from ..integrations import claude_client, gemini_client, hume_client
from ..models import AuditLog, Ticket, Transaction, Verification
from ..schemas import (
    GeminiSummary,
    HumeScores,
    WsServerDecision,
    WsServerError,
    WsServerGeminiPartial,
    WsServerHumePartial,
    WsServerReady,
)
from ..util import new_id

router = APIRouter()
log = structlog.get_logger()


def _delta_vs_baseline(scores: HumeScores, baseline: HumeScores | None) -> dict[str, float] | None:
    if baseline is None:
        return None
    return {
        "fear": max(0.0, scores.fear - baseline.fear),
        "distress": max(0.0, scores.distress - baseline.distress),
        "anxiety": max(0.0, scores.anxiety - baseline.anxiety),
    }


@router.websocket("/ws/verify/{verification_id}")
async def verify_ws(websocket: WebSocket, verification_id: str) -> None:
    # WS routes bypass HTTP middleware — bind the per-visitor session manually
    # from the ?sid= query string before touching the DB or embedding cache.
    sid = websocket.query_params.get("sid")
    if not sid:
        await websocket.accept()
        await websocket.send_json(WsServerError(reason="missing_session_id").model_dump())
        await websocket.close()
        return
    sess = session_manager.get_or_create(sid)
    token = session_manager.bind(sess)

    await websocket.accept()
    db: Session = SessionLocal()
    try:
        verification = db.get(Verification, verification_id)
        if not verification:
            await websocket.send_json(WsServerError(reason="verification_not_found").model_dump())
            await websocket.close()
            return
        if verification.status == "COMPLETE":
            await websocket.send_json(WsServerError(reason="verification_already_completed").model_dump())
            await websocket.close()
            return

        transaction = db.get(Transaction, verification.transaction_id)
        if not transaction:
            await websocket.send_json(WsServerError(reason="transaction_not_found").model_dump())
            await websocket.close()
            return

        # Generate Q's up front so the frontend can pre-load TTS. Cheap (~1-2s).
        questions = await claude_client.generate_questions(
            tier=transaction.tier,  # type: ignore[arg-type]
            amount_eur=transaction.amount_eur,
            merchant=transaction.merchant,
            merchant_reputation=transaction.merchant_reputation,  # type: ignore[arg-type]
            risk_signals=verification.risk_signals,
        )

        await websocket.send_json(
            WsServerReady(tier=transaction.tier, questions=questions).model_dump()  # type: ignore[arg-type]
        )

        # Per-question state
        current_q_pcm: dict[str, bytearray] = {}  # q_id -> accumulated PCM
        q_buckets: list[dict] = []  # final per-Q records after answer_end
        baseline_scores: HumeScores | None = None

        # Legacy state (for clients that don't send q_id)
        legacy_pcm = bytearray()

        # HIGH_RISK state
        jpeg_frames: list[bytes] = []
        client_gemini: GeminiSummary | None = None

        while True:
            msg = await websocket.receive_json()
            kind = msg.get("type")

            if kind == "start":
                continue

            if kind == "audio_chunk":
                try:
                    audio = base64.b64decode(msg.get("data", ""))
                except Exception:  # noqa: BLE001
                    await websocket.send_json(WsServerError(reason="bad_audio_b64").model_dump())
                    continue
                q_id = msg.get("q_id")
                if q_id:
                    current_q_pcm.setdefault(q_id, bytearray()).extend(audio)
                else:
                    legacy_pcm.extend(audio)
                continue

            if kind == "answer_end":
                q_id = msg.get("q_id")
                transcript = (msg.get("transcript") or "").strip()
                if not q_id:
                    await websocket.send_json(WsServerError(reason="answer_end_missing_q_id").model_dump())
                    continue
                pcm = bytes(current_q_pcm.pop(q_id, bytearray()))
                q_def = next((q for q in questions if q.get("id") == q_id), None)
                if q_def is None:
                    await websocket.send_json(WsServerError(reason=f"unknown_q_id:{q_id}").model_dump())
                    continue
                # Score this answer with Hume.
                if pcm:
                    scores = await hume_client.score_audio(pcm)
                else:
                    # No audio captured — return a service_available=false placeholder.
                    scores = HumeScores(
                        verdict_hint="AMBIGUOUS",
                        service_available=False,
                        note="no audio captured for this question",
                    )

                is_baseline = q_def.get("purpose") == "baseline"
                if is_baseline and baseline_scores is None:
                    baseline_scores = scores

                delta = _delta_vs_baseline(scores, None if is_baseline else baseline_scores)
                bucket = {
                    "id": q_id,
                    "text": q_def["text"],
                    "purpose": q_def["purpose"],
                    "transcript": transcript,
                    "hume_scores": scores.model_dump(),
                    "is_baseline": is_baseline,
                    "delta_vs_baseline": delta,
                }
                q_buckets.append(bucket)

                await websocket.send_json(
                    WsServerHumePartial(
                        scores=scores, q_id=q_id, delta_vs_baseline=delta
                    ).model_dump()
                )
                continue

            if kind == "video_frame":
                try:
                    jpeg_frames.append(base64.b64decode(msg.get("data", "")))
                except Exception:  # noqa: BLE001
                    await websocket.send_json(WsServerError(reason="bad_video_b64").model_dump())
                continue

            if kind == "client_gemini":
                # Frontend forwards its own Gemini Live summary. Echo it back
                # for the UI and store it for Claude.decide.
                try:
                    summary_data = msg.get("summary") or {}
                    client_gemini = GeminiSummary.model_validate(summary_data)
                    await websocket.send_json(
                        WsServerGeminiPartial(summary=client_gemini).model_dump()
                    )
                except Exception:  # noqa: BLE001
                    await websocket.send_json(WsServerError(reason="bad_client_gemini").model_dump())
                continue

            if kind == "end":
                break

            await websocket.send_json(WsServerError(reason=f"unknown_type:{kind}").model_dump())

        # Verification complete — run final decision.
        await _finalize_verification(
            db=db,
            websocket=websocket,
            verification=verification,
            transaction=transaction,
            q_buckets=q_buckets,
            legacy_pcm=bytes(legacy_pcm),
            jpeg_frames=jpeg_frames,
            client_gemini=client_gemini,
        )

    except WebSocketDisconnect:
        log.info("ws_disconnect", verification_id=verification_id)
    except Exception as e:  # noqa: BLE001
        log.exception("ws_error", verification_id=verification_id, error=str(e))
        try:
            await websocket.send_json(WsServerError(reason=f"internal:{e}").model_dump())
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()
        session_manager.unbind(token)


async def _finalize_verification(
    db: Session,
    websocket: WebSocket,
    verification: Verification,
    transaction: Transaction,
    q_buckets: list[dict],
    legacy_pcm: bytes,
    jpeg_frames: list[bytes],
    client_gemini: GeminiSummary | None,
) -> None:
    from datetime import datetime

    started_at = verification.created_at
    decided_at = datetime.utcnow()

    # Aggregated Hume bucket — use the worst non-baseline answer if we have
    # per-Q buckets, otherwise fall through to the legacy path.
    aggregated_hume: HumeScores | None = None
    if q_buckets:
        non_baseline = [b for b in q_buckets if not b["is_baseline"]]
        chosen = max(non_baseline, key=lambda b: b["hume_scores"].get("fear", 0.0)
                     + b["hume_scores"].get("distress", 0.0), default=None)
        if chosen is None and q_buckets:
            chosen = q_buckets[0]
        if chosen:
            aggregated_hume = HumeScores.model_validate(chosen["hume_scores"])
    elif legacy_pcm:
        aggregated_hume = await hume_client.score_audio(legacy_pcm)

    # Gemini: prefer the client-forwarded summary; fall back to the backend
    # path (which itself falls back to mock if disabled / failing).
    gemini_summary = client_gemini
    if gemini_summary is None and transaction.tier == "HIGH_RISK":
        gemini_summary = await gemini_client.analyze_av(jpeg_frames, legacy_pcm or None)

    verdict = await claude_client.decide(
        tier=transaction.tier,  # type: ignore[arg-type]
        hume=aggregated_hume,
        gemini=gemini_summary,
        merchant_reputation=transaction.merchant_reputation,  # type: ignore[arg-type]
        amount_eur=transaction.amount_eur,
        merchant=transaction.merchant,
        user_id=transaction.user_id,
        questions=q_buckets if q_buckets else None,
        risk_signals=verification.risk_signals,
    )

    duration_ms = int((decided_at - started_at).total_seconds() * 1000)
    audit = AuditLog(
        id=new_id("aud"),
        verification_id=verification.id,
        transaction_id=transaction.id,
        tier=transaction.tier,
        hume_scores=aggregated_hume.model_dump() if aggregated_hume else None,
        gemini_summary=gemini_summary.model_dump() if gemini_summary else None,
        merchant_reputation=transaction.merchant_reputation,
        verdict=verdict.model_dump(),
        risk_signals=verification.risk_signals,
        questions=q_buckets or None,
        started_at=started_at,
        decided_at=decided_at,
        duration_ms=duration_ms,
    )
    db.add(audit)

    status_map = {
        "APPROVED": "APPROVED",
        "HELD_FOR_REVIEW": "HELD_FOR_REVIEW",
        "FROZEN": "FROZEN",
    }
    transaction.status = status_map[verdict.verdict]
    verification.status = "COMPLETE"
    verification.questions = q_buckets or None

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
        tier=transaction.tier,
        verdict=verdict.verdict,
        duration_ms=duration_ms,
        question_count=len(q_buckets),
        hume_ok=aggregated_hume is not None,
        gemini_ok=gemini_summary is not None or transaction.tier != "HIGH_RISK",
    )

    # Emit final hume_partial (legacy clients) and gemini_partial echoes,
    # then the decision. Non-Q audio paths (mock smoke) need the legacy emit.
    if not q_buckets and aggregated_hume is not None:
        await websocket.send_json(WsServerHumePartial(scores=aggregated_hume).model_dump())
    if not client_gemini and gemini_summary is not None and transaction.tier == "HIGH_RISK":
        await websocket.send_json(WsServerGeminiPartial(summary=gemini_summary).model_dump())
    await websocket.send_json(
        WsServerDecision(
            verdict=verdict.verdict,
            rationale=verdict.rationale,
            audit_log_id=audit.id,
        ).model_dump()
    )
    await websocket.close()

"""WebSocket verification endpoint.

Client sends JSON envelopes:
  {"type": "start"}
  {"type": "audio_chunk", "data": "<base64 pcm16 16kHz mono>"}
  {"type": "video_frame", "data": "<base64 jpeg>"}   # HIGH_RISK only
  {"type": "end"}

Server emits:
  {"type": "ready", "tier": "..."}
  {"type": "hume_partial", "scores": {...}}
  {"type": "gemini_partial", "summary": {...}}
  {"type": "decision", "verdict": "...", "rationale": "...", "audit_log_id": "..."}
  {"type": "error", "reason": "..."}
"""

from __future__ import annotations

import base64

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Transaction, Verification
from ..schemas import (
    WsServerDecision,
    WsServerError,
    WsServerGeminiPartial,
    WsServerHumePartial,
    WsServerReady,
)
from ..services.orchestrator import run_verification

router = APIRouter()
log = structlog.get_logger()


@router.websocket("/ws/verify/{verification_id}")
async def verify_ws(websocket: WebSocket, verification_id: str) -> None:
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

        await websocket.send_json(WsServerReady(tier=transaction.tier).model_dump())  # type: ignore[arg-type]

        pcm_audio = bytearray()
        jpeg_frames: list[bytes] = []
        while True:
            msg = await websocket.receive_json()
            kind = msg.get("type")
            if kind == "start":
                continue
            if kind == "audio_chunk":
                try:
                    pcm_audio.extend(base64.b64decode(msg.get("data", "")))
                except Exception:  # noqa: BLE001
                    await websocket.send_json(WsServerError(reason="bad_audio_b64").model_dump())
                continue
            if kind == "video_frame":
                try:
                    jpeg_frames.append(base64.b64decode(msg.get("data", "")))
                except Exception:  # noqa: BLE001
                    await websocket.send_json(WsServerError(reason="bad_video_b64").model_dump())
                continue
            if kind == "end":
                break
            await websocket.send_json(WsServerError(reason=f"unknown_type:{kind}").model_dump())

        verdict, audit, hume_scores, gemini_summary = await run_verification(
            db=db,
            verification=verification,
            transaction=transaction,
            pcm_audio=bytes(pcm_audio),
            jpeg_frames=jpeg_frames,
        )

        if hume_scores is not None:
            await websocket.send_json(WsServerHumePartial(scores=hume_scores).model_dump())
        if gemini_summary is not None:
            await websocket.send_json(WsServerGeminiPartial(summary=gemini_summary).model_dump())
        await websocket.send_json(
            WsServerDecision(
                verdict=verdict.verdict,
                rationale=verdict.rationale,
                audit_log_id=audit.id,
            ).model_dump()
        )
        await websocket.close()
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

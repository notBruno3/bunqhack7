"""Gemini Live integration — environment + duress analysis from video frames.

Real path opens a Gemini Live session, streams the collected JPEG frames
(and optionally audio), then asks the model for a structured JSON summary.
Mock path returns a canned GeminiSummary.
"""

from __future__ import annotations

import json

import structlog

from ..config import settings
from ..schemas import GeminiSummary
from ..state import state
from . import mocks

log = structlog.get_logger()

_PROMPT = """Analyze this short video + audio clip of a user confirming a bank transaction.
Return STRICT JSON with keys:
- location_type (one of: home_indoor, office, public_outdoor, public_unfamiliar, vehicle, unknown)
- duress_signals (list of strings; empty if none. Examples: second_person_visible, user_glances_offscreen, low_light, partial_face_cover, signs_of_struggle)
- confidence (0..1)
- raw_text (1-2 sentence human-readable summary)
Respond with ONLY the JSON object."""


async def analyze_av(jpeg_frames: list[bytes], audio_pcm: bytes | None) -> GeminiSummary:
    if state.mock_mode or not settings.google_api_key:
        return mocks.gemini_for(state.scenario)

    try:
        return await _analyze_real(jpeg_frames, audio_pcm)
    except Exception as e:  # noqa: BLE001
        log.warning("gemini_failed", error=str(e))
        fallback = mocks.gemini_for(state.scenario)
        return fallback.model_copy(update={"service_available": False})


async def _analyze_real(jpeg_frames: list[bytes], audio_pcm: bytes | None) -> GeminiSummary:
    from google import genai  # type: ignore[import-not-found]

    client = genai.Client(api_key=settings.google_api_key)
    parts: list[dict] = [{"text": _PROMPT}]
    for frame in jpeg_frames[-8:]:  # cap to ~8 frames to keep the request small
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": frame}})
    if audio_pcm:
        parts.append({"inline_data": {"mime_type": "audio/pcm", "data": audio_pcm}})

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[{"role": "user", "parts": parts}],
        config={"response_mime_type": "application/json"},
    )
    text = (response.text or "").strip()
    data = json.loads(text) if text else {}
    return GeminiSummary(
        location_type=data.get("location_type", "unknown"),
        duress_signals=list(data.get("duress_signals") or []),
        confidence=float(data.get("confidence", 0.0)),
        raw_text=data.get("raw_text", text[:500]),
    )

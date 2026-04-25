"""Gemini integration — environment analysis (frontend-driven) and embeddings.

The frontend now opens its own Gemini Live session and forwards summaries via
the WS as `client_gemini` events; the backend's analyze_av path remains as a
fallback when the frontend can't (or won't) supply a summary.

The embed_text helper uses gemini-embedding-2 (multimodal-capable, GA 2026-04-22)
for the behavioral risk classifier in services/risk_embeddings.py.
"""

from __future__ import annotations

import json

import structlog

from ..config import settings
from ..schemas import GeminiSummary
from ..state import state
from . import mocks

log = structlog.get_logger()

EMBED_MODEL = "gemini-embedding-2"
EMBED_DIM = 768  # MRL truncation — plenty for ~100 vectors per user


async def embed_text(text: str) -> list[float] | None:
    """Embed a single string with gemini-embedding-2. Returns None if unavailable."""
    if state.mock_mode or not settings.google_api_key:
        return None
    try:
        from google import genai

        client = genai.Client(api_key=settings.google_api_key)
        resp = await client.aio.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
            config={"output_dimensionality": EMBED_DIM},
        )
        if not getattr(resp, "embeddings", None):
            return None
        return list(resp.embeddings[0].values)
    except Exception as e:  # noqa: BLE001
        log.warning("embed_failed", error=str(e), text_preview=text[:80])
        return None


async def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """Batch-embed many strings in a single API call.

    Returns a list aligned with `texts`; entries are None for any individual
    embedding that failed (whole-batch failure → all None).
    """
    if not texts:
        return []
    if state.mock_mode or not settings.google_api_key:
        return [None] * len(texts)
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.google_api_key)
        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
        resp = await client.aio.models.embed_content(
            model=EMBED_MODEL,
            contents=contents,
            config={"output_dimensionality": EMBED_DIM},
        )
        embs = getattr(resp, "embeddings", None) or []
        out: list[list[float] | None] = []
        for i in range(len(texts)):
            if i < len(embs) and embs[i] is not None:
                out.append(list(embs[i].values))
            else:
                out.append(None)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("embed_batch_failed", error=str(e), count=len(texts))
        return [None] * len(texts)

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
    """One-shot multimodal call. Audio omitted — Gemini doesn't take raw PCM
    via generate_content, and the per-question Hume scoring already covers the
    voice signal. Frames-only is the right shape for environment analysis.
    """
    import base64

    from google import genai  # type: ignore[import-not-found]

    if not jpeg_frames:
        # No frames to analyze — return a neutral summary.
        return GeminiSummary(
            location_type="unknown",
            duress_signals=[],
            confidence=0.0,
            raw_text="No video frames captured.",
        )

    client = genai.Client(api_key=settings.google_api_key)
    parts: list[dict] = [{"text": _PROMPT}]
    for frame in jpeg_frames[-8:]:  # cap to ~8 frames to keep the request small
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(frame).decode(),
            }
        })

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

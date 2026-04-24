"""Hume Expression Measurement integration.

The real path uses Hume's streaming WebSocket via the official SDK. We
collect the client-streamed audio chunks into one buffer and submit it;
this keeps latency acceptable while avoiding chunk-boundary issues.

The wrapper ALWAYS returns a HumeScores; errors flip service_available
to False so the orchestrator can still produce a verdict.
"""

from __future__ import annotations

import structlog

from ..config import settings
from ..schemas import HumeScores
from ..state import state
from . import mocks

log = structlog.get_logger()


async def score_audio(pcm_bytes: bytes) -> HumeScores:
    if state.mock_mode or not settings.hume_api_key:
        return mocks.hume_for(state.scenario)

    try:
        return await _score_real(pcm_bytes)
    except Exception as e:  # noqa: BLE001 — provider failures must not kill verification
        log.warning("hume_failed", error=str(e))
        fallback = mocks.hume_for(state.scenario)
        return fallback.model_copy(update={"service_available": False, "note": f"hume error: {e}"})


async def _score_real(pcm_bytes: bytes) -> HumeScores:
    """Submit a combined PCM16 16kHz mono buffer to Hume and normalize the result.

    Hume returns per-emotion scores (48+ categories). We collapse the most
    relevant prosody dimensions into calmness / fear / distress / anxiety.
    """
    from hume import AsyncHumeClient
    from hume.expression_measurement.stream import Config
    from hume.expression_measurement.stream.socket_client import StreamConnectOptions

    client = AsyncHumeClient(api_key=settings.hume_api_key)
    options = StreamConnectOptions(config=Config(prosody={}))

    aggregate: dict[str, list[float]] = {}
    async with client.expression_measurement.stream.connect(options=options) as socket:
        result = await socket.send_bytes(pcm_bytes)
        for prediction in getattr(result, "prosody", {}).get("predictions", []) or []:
            for emotion in prediction.get("emotions", []):
                aggregate.setdefault(emotion["name"], []).append(emotion["score"])

    def avg(name: str) -> float:
        values = aggregate.get(name, [])
        return sum(values) / len(values) if values else 0.0

    calmness = max(avg("Calmness"), avg("Contentment"))
    fear = max(avg("Fear"), avg("Horror"))
    distress = max(avg("Distress"), avg("Anxiety"))
    anxiety = avg("Anxiety")

    hint: str
    if calmness > 0.6 and fear < 0.2 and distress < 0.2:
        hint = "CLEAN"
    elif fear > 0.5 or distress > 0.5:
        hint = "FLAGGED"
    else:
        hint = "AMBIGUOUS"

    return HumeScores(
        calmness=calmness,
        fear=fear,
        distress=distress,
        anxiety=anxiety,
        confidence_overall=max(calmness, fear, distress),
        verdict_hint=hint,  # type: ignore[arg-type]
        note=f"Aggregated over {sum(len(v) for v in aggregate.values())} emotion samples.",
    )

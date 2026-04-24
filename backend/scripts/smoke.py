"""End-to-end smoke test. Assumes the server is running locally on PORT (default 8000).

Runs in MOCK_MODE — exercises every endpoint + one WebSocket verification.
Prints a compact pass/fail summary; exits non-zero on the first failure.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from typing import Any

import httpx
import websockets

BASE = f"http://localhost:{os.environ.get('PORT', '8000')}"
WS_BASE = f"ws://localhost:{os.environ.get('PORT', '8000')}"


def _assert(cond: bool, label: str, payload: Any = None) -> None:
    if cond:
        print(f"  OK  {label}")
        return
    print(f"  FAIL {label}")
    if payload is not None:
        print(json.dumps(payload, indent=2, default=str))
    sys.exit(1)


async def _ws_verify(verification_id: str, send_video: bool = False) -> dict:
    async with websockets.connect(f"{WS_BASE}/ws/verify/{verification_id}") as ws:
        ready = json.loads(await ws.recv())
        _assert(ready["type"] == "ready", "ws ready received", ready)

        await ws.send(json.dumps({"type": "start"}))
        # 160 ms of silence at 16kHz pcm16 is enough to trip the pipeline in mock mode.
        silent = bytes(16000 * 2 // 5)
        await ws.send(
            json.dumps({"type": "audio_chunk", "data": base64.b64encode(silent).decode()})
        )
        if send_video:
            tiny_jpeg = bytes.fromhex(
                "ffd8ffe000104a46494600010100000100010000ffdb0043"
                "000302020302020303030304030304050805050404050a07"
                "0706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016"
                "161113141513ffd9"
            )
            await ws.send(
                json.dumps({"type": "video_frame", "data": base64.b64encode(tiny_jpeg).decode()})
            )
        await ws.send(json.dumps({"type": "end"}))

        decision = None
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == "decision":
                decision = msg
                break
        _assert(decision is not None, "ws decision received")
        return decision  # type: ignore[return-value]


async def main() -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{BASE}/health")
        _assert(r.status_code == 200 and r.json()["ok"], "GET /health", r.text)

        r = await client.post(f"{BASE}/api/mock/toggle", json={"mock": True})
        _assert(r.status_code == 200 and r.json()["mock_mode"], "mock on", r.text)

        r = await client.post(f"{BASE}/api/mock/reset")
        _assert(r.status_code == 200, "mock reset", r.text)

        # --- NO_RISK path
        r = await client.post(
            f"{BASE}/api/transaction/initiate",
            json={"amount_eur": 12.0, "merchant": "Albert Heijn"},
        )
        body = r.json()
        _assert(
            r.status_code == 200 and body["tier"] == "NO_RISK" and body["status"] == "APPROVED",
            "NO_RISK initiate",
            body,
        )

        # --- MID_RISK flagged path
        await client.post(f"{BASE}/api/mock/scenario/mid_flagged")
        r = await client.post(
            f"{BASE}/api/transaction/initiate",
            json={"amount_eur": 600.0, "merchant": "Etsy"},
        )
        body = r.json()
        _assert(body["tier"] == "MID_RISK" and body["verification_id"], "MID_RISK initiate", body)
        decision = await _ws_verify(body["verification_id"], send_video=False)
        _assert(
            decision["verdict"] in {"HELD_FOR_REVIEW", "FROZEN"},
            "MID_RISK flagged -> held",
            decision,
        )

        # --- HIGH_RISK fail path
        await client.post(f"{BASE}/api/mock/scenario/high_fail")
        r = await client.post(
            f"{BASE}/api/transaction/initiate",
            json={"amount_eur": 5000.0, "merchant": "Unknown LLP"},
        )
        body = r.json()
        _assert(body["tier"] == "HIGH_RISK" and body["verification_id"], "HIGH_RISK initiate", body)
        decision = await _ws_verify(body["verification_id"], send_video=True)
        _assert(decision["verdict"] == "FROZEN", "HIGH_RISK fail -> frozen", decision)

        # --- Admin tickets populated
        r = await client.get(f"{BASE}/api/admin/tickets")
        tickets = r.json()
        _assert(r.status_code == 200 and len(tickets) >= 2, "admin tickets listed", tickets)

        tkt_id = tickets[0]["id"]
        r = await client.post(
            f"{BASE}/api/admin/tickets/{tkt_id}/decision",
            json={"action": "approve", "note": "smoke test override"},
        )
        _assert(r.status_code == 200 and r.json()["status"] == "APPROVED", "ticket decision", r.text)

    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    asyncio.run(main())

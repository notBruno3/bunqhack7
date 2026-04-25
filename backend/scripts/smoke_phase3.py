"""Phase 3 smoke — embedding classifier in action.

Confirms the classifier picks the right tier from real signals (no scenario
pinning), prints the score components so we can eyeball calibration.
"""

from __future__ import annotations

import asyncio
import json

import httpx

BASE = "http://localhost:8000"


async def classify_one(client, label, merchant, amount):
    print(f"\n=== {label}: {merchant} €{amount}")
    # Reset to known state
    await client.post(f"{BASE}/api/mock/scenario/clear")
    r = await client.post(
        f"{BASE}/api/transaction/initiate",
        json={"amount_eur": amount, "merchant": merchant},
    )
    body = r.json()
    print(f"  Tier: {body['tier']}")
    print(f"  Status: {body['status']}")
    print(f"  Reputation: {body['merchant_reputation']}")

    # Pull the most recent audit log to inspect risk_signals
    audits = (await client.get(f"{BASE}/api/admin/audit_logs")).json()
    last = audits[0] if audits else None
    if last and last.get("risk_signals"):
        s = last["risk_signals"]
        print(f"  Descriptor: {s['descriptor']}")
        print(f"  Risk score: {s['risk']:.3f} "
              f"(n_emb={s['n_emb']:.3f} n_amt={s['n_amt']:.3f} "
              f"n_time={s['n_time']:.3f} p_merch={s['p_merch']:.3f})")
    elif last:
        print(f"  Risk signals: not present (cold start or fallback path)")


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(f"{BASE}/api/mock/reset")
        # Wait for embedding re-init after reset
        for _ in range(60):
            r = await client.get(f"{BASE}/api/transactions")
            if len(r.json()) >= 50:
                break
            await asyncio.sleep(1)

        # The three demo transactions
        await classify_one(client, "Regular", "Albert Heijn", 38.20)
        await classify_one(client, "Suspicious", "FastWire", 600.00)
        await classify_one(client, "Fraudulent", "Unknown LLP", 5000.00)

        # Bonus: a near-novel-but-benign tx for calibration
        await classify_one(client, "Edge: large legit", "KLM", 450.00)
        await classify_one(client, "Edge: tiny novel merchant", "Random Cafe", 4.50)


if __name__ == "__main__":
    asyncio.run(main())

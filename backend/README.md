# Consent — Backend

Transaction intent verification backend. FastAPI app exposing:

- `POST /api/transaction/initiate` — classifies a transaction into `NO_RISK` / `MID_RISK` / `HIGH_RISK`
- `WS  /ws/verify/{verification_id}` — streams audio (and video for HIGH) to Hume + Gemini, calls Claude, returns a verdict
- `GET /api/admin/tickets` + `POST /api/admin/tickets/{id}/decision` — compliance dashboard
- `POST /api/mock/scenario/{name}` + `/api/mock/force_tier` + `/api/mock/reset` + `/api/mock/toggle` — demo operator controls

## Quickstart

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env         # MOCK_MODE=true by default — no keys needed
./scripts/dev.sh             # http://localhost:8000 ; docs at /docs
```

## Mock vs. real

`MOCK_MODE=true` short-circuits every provider integration with canned results keyed by the
active scenario (set via `POST /api/mock/scenario/{name}`). Use this for FE development and as
a live-demo fallback if the venue WiFi fails.

Flip at runtime: `curl -X POST :8000/api/mock/toggle -d '{"mock": false}'`.

## Demo script

```bash
# Scenario 1 — MID_RISK clean
curl -X POST :8000/api/mock/scenario/mid_clean
curl -X POST :8000/api/transaction/initiate \
     -H 'content-type: application/json' \
     -d '{"amount_eur": 600, "merchant": "Etsy"}'
# -> open the returned ws_url from the frontend

# Scenario 2 — HIGH_RISK flagged
curl -X POST :8000/api/mock/scenario/high_fail
curl -X POST :8000/api/transaction/initiate \
     -H 'content-type: application/json' \
     -d '{"amount_eur": 5000, "merchant": "Unknown LLP"}'
```

## Smoke test

`python scripts/smoke.py` — hits every endpoint end-to-end in mock mode.

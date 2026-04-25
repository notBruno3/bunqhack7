from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .routes import admin, mock_control, transactions, verify
from .services import embedding_cache, mock_bunq
from .state import state

logging.basicConfig(level=logging.INFO, format="%(message)s")
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    mock_bunq.seed_if_empty()
    state.mock_mode = settings.mock_mode
    log.info("startup", mock_mode=state.mock_mode, db_url=settings.db_url)
    # Pre-embed the user's seeded history so first-call latency is cheap.
    # Best-effort: if Google API is down, the risk scorer falls back to the
    # amount-threshold rule transparently.
    try:
        await embedding_cache.initialize()
        log.info("embedding_cache_ready", size=embedding_cache.cache_size())
    except Exception as e:  # noqa: BLE001
        log.warning("embedding_cache_init_failed", error=str(e))
    yield


app = FastAPI(title="Consent Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router, prefix="/api", tags=["transactions"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(mock_control.router, prefix="/api/mock", tags=["mock"])
app.include_router(verify.router, tags=["verify"])  # WebSocket — no /api prefix


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"ok": True, "mock_mode": state.mock_mode}

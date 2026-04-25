from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from . import session_manager
from .config import settings
from .routes import admin, mock_control, transactions, verify
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

# Routes that intentionally don't require a session-id (status/health probes).
_OPEN_PATHS = {"/health"}


def _resolve_session_id(request: Request) -> str | None:
    sid = request.headers.get("x-session-id")
    if sid:
        return sid
    return request.query_params.get("sid")


class SessionMiddleware(BaseHTTPMiddleware):
    """Bind the current session for the duration of each HTTP request.

    Looks up X-Session-Id (or ?sid=) on the request, lazily creates a fresh
    in-memory DB + seeded history if it's a new id, and binds it to a
    ContextVar so db.SessionLocal()/state/embedding_cache route to it.
    WebSocket routes don't go through Starlette HTTP middleware — they
    bind manually inside the handler.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _OPEN_PATHS:
            return await call_next(request)
        sid = _resolve_session_id(request)
        if not sid:
            # No session id supplied. Let it through unbound — endpoints that
            # need a session will raise; /health and friends won't.
            return await call_next(request)
        sess = session_manager.get_or_create(sid)
        # Seed the per-session demo_state.mock_mode from settings on first hit.
        if not getattr(sess, "_mock_mode_initialized", False):
            sess.demo_state.mock_mode = settings.mock_mode
            sess._mock_mode_initialized = True  # type: ignore[attr-defined]
        token = session_manager.bind(sess)
        try:
            return await call_next(request)
        finally:
            session_manager.unbind(token)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # No global DB seeding here anymore — each visitor's session is created
    # and seeded lazily on first request inside SessionMiddleware.
    log.info("startup", mock_mode=settings.mock_mode, db_url=settings.db_url)
    yield


app = FastAPI(title="Consent Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(SessionMiddleware)
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
    return {
        "ok": True,
        "mock_mode": settings.mock_mode,
        "active_sessions": session_manager.session_count(),
    }

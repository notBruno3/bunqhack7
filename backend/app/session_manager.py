"""Per-visitor session isolation.

Each browser session gets its own in-memory SQLite database, embedding cache,
and demo-state knobs. A ContextVar binds the "current session" for the lifetime
of an HTTP request or WebSocket; module-level shims in db.py / state.py /
embedding_cache.py read that variable so existing call sites don't change.

Session id is supplied by the client (X-Session-Id header for HTTP, ?sid=
query param for WebSocket). Unknown ids auto-create a fresh seeded session.
"""

from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .state import DemoState

log = structlog.get_logger()


@dataclass
class Session:
    id: str
    engine: Any
    SessionLocal: Any
    embed_cache: dict[str, np.ndarray] = field(default_factory=dict)
    embed_init_done: bool = False
    embed_init_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    demo_state: DemoState = field(default_factory=DemoState)


_REGISTRY: dict[str, Session] = {}
_REGISTRY_LOCK = threading.Lock()
_CURRENT: ContextVar[Session | None] = ContextVar("current_session", default=None)


def _build_session(session_id: str) -> Session:
    """Create a fresh in-memory SQLite engine + tables, then seed history.

    StaticPool keeps a single connection alive — without it, each SQLAlchemy
    session would get a new (empty) :memory: database.
    """
    # Local imports break a cycle: db -> session_manager -> models -> ...
    from . import models
    from .services import mock_bunq

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SessionLocal = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, future=True
    )
    models.Base.metadata.create_all(engine)

    s = Session(id=session_id, engine=engine, SessionLocal=SessionLocal)

    # Bind so seed_if_empty() (which calls SessionLocal()) routes here.
    token = _CURRENT.set(s)
    try:
        mock_bunq.seed_if_empty()
    finally:
        _CURRENT.reset(token)

    log.info("session_created", session_id=session_id)
    return s


def get_or_create(session_id: str) -> Session:
    with _REGISTRY_LOCK:
        s = _REGISTRY.get(session_id)
        if s is None:
            s = _build_session(session_id)
            _REGISTRY[session_id] = s
        return s


def drop(session_id: str) -> None:
    """Remove a session from the registry. Next access recreates it."""
    with _REGISTRY_LOCK:
        s = _REGISTRY.pop(session_id, None)
        if s is not None:
            try:
                s.engine.dispose()
            except Exception:  # noqa: BLE001
                pass
            log.info("session_dropped", session_id=session_id)


def current() -> Session:
    s = _CURRENT.get()
    if s is None:
        raise RuntimeError(
            "No session bound to current context. "
            "Did the client send X-Session-Id / ?sid=?"
        )
    return s


def current_or_none() -> Session | None:
    return _CURRENT.get()


def bind(session: Session) -> Token:
    return _CURRENT.set(session)


def unbind(token: Token) -> None:
    _CURRENT.reset(token)


def session_count() -> int:
    return len(_REGISTRY)

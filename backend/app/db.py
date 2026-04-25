"""DB facade — routes every session through the per-visitor session manager.

Call sites still write `from .db import SessionLocal` and call `SessionLocal()`,
or use `Depends(get_db)`. Both resolve to the in-memory engine owned by the
current session (bound by middleware on HTTP and by the WS handler).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from . import session_manager


def SessionLocal() -> Session:
    """Return a SQLAlchemy session bound to the current request's engine."""
    return session_manager.current().SessionLocal()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """No-op kept for backwards compatibility.

    Per-session engines are created and tables built lazily inside
    `session_manager.get_or_create`.
    """
    return None

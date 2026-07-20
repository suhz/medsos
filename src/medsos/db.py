"""SQLAlchemy engine + session factory."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from medsos.config import get_settings
from medsos.models import Base  # noqa: F401  (registers tables on Base.metadata)

_engine: Engine | None = None
_engine_url: str | None = None
_SessionLocal: sessionmaker[Session] | None = None
_sessionmaker_url: str | None = None


def _current_db_url() -> str:
    """Resolve current db_url: prefer fresh env (test monkeypatch) over cached Settings."""
    env_url = os.environ.get("MEDSOS_DB_URL")
    if env_url:
        return env_url
    return get_settings().db_url


def _get_engine() -> Engine:
    global _engine, _engine_url
    url = _current_db_url()
    if _engine is None or _engine_url != url:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine(url, future=True, pool_pre_ping=True)
        _engine_url = url
    return _engine


def engine() -> Engine:
    return _get_engine()


def _get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal, _sessionmaker_url
    url = _current_db_url()
    if _SessionLocal is None or _sessionmaker_url != url:
        _SessionLocal = sessionmaker(bind=_get_engine(), expire_on_commit=False, future=True)
        _sessionmaker_url = url
    return _SessionLocal


def SessionLocal() -> Session:  # type: ignore[no-redef]
    return _get_sessionmaker()()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    """Create all tables. For tests / simple setups (Alembic handles prod)."""
    Base.metadata.create_all(bind=_get_engine())
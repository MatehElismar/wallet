"""Lazy SQLAlchemy engine and session-factory construction.

No connection is opened at import time or while creating an engine. Callers
must supply already-validated :class:`wallet_v2.config.Settings`; this keeps
runtime wiring explicit and lets tests inspect configuration without touching
a database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from wallet_v2.config import Settings


def create_engine_from_settings(settings: Settings) -> Engine:
    """Build, but do not connect, a PostgreSQL engine from ``settings``."""

    return create_engine(
        settings.database.url,
        echo=settings.database.echo,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a non-autocommitting session factory bound to ``engine``."""

    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a transactional session, committing on success and rolling back on error."""

    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()

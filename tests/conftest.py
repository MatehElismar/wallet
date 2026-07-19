"""Pytest configuration for Wallet V2 tests.

The test suite is hermetic: it never touches the network, never reads
``os.environ``, and never connects to a live database. Domain-layer
tests run without any fixture; schema tests build an in-memory SQLite
engine to validate constraint behaviour.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from wallet_v2.persistence.base import Base
from wallet_v2.persistence.models import *  # noqa: F401,F403 - register all


@pytest.fixture()
def sqlite_engine() -> Iterator[Engine]:
    """An in-memory SQLite engine with all V2 tables created.

    SQLite does not enforce ``CHECK`` constraints by default; we enable
    foreign keys and check enforcement so the constraint tests are
    meaningful. JSONB falls back to TEXT under SQLite via SQLAlchemy's
    dialect handling, so JSON columns round-trip as Python dicts.
    """

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        future=True,
    )
    # SQLite needs PRAGMA foreign_keys=ON to honour FK constraints.
    from sqlalchemy import event, text

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn: Any, _records: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def session(sqlite_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture()
def metadata_tables() -> dict[str, Any]:
    """Return a mapping of table name -> table object from the ORM metadata."""

    return dict(inspect(Base.metadata).sorted_tables)

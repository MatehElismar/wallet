"""Project-specific SQLAlchemy column types.

* :class:`JSONB` — a portable JSONB type that renders as native ``JSONB``
  on PostgreSQL and falls back to ``JSON`` (stored as TEXT) on SQLite.
  The ORM models use this type so the same model definitions work both
  against the production PostgreSQL database and the in-memory SQLite
  engine used by the hermetic test suite. The hand-written Alembic
  migration uses ``sqlalchemy.dialects.postgresql.JSONB`` directly so
  the production DDL is explicit and reviewable.
"""

from __future__ import annotations

from sqlalchemy import JSON, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB as _PgJSONB


class JSONB(TypeDecorator):
    """JSONB on PostgreSQL, JSON on every other backend.

    ``TypeDecorator`` lets the same ORM column declaration render as
    ``JSONB`` when targeting PostgreSQL (preserving the binary JSON
    index/query semantics the production schema relies on) and as plain
    ``JSON`` when targeting SQLite (so the in-memory test engine can
    create the tables without a ``JSONB`` type it cannot render).
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgJSONB())
        return dialect.type_descriptor(JSON())


__all__ = ["JSONB"]

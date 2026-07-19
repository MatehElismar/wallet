"""Declarative base and shared mixins for Wallet V2 models.

Two mixins encode the project's cross-cutting invariants:

* :class:`Timestamped` adds ``created_at`` and ``updated_at`` columns. Use
  this for tables whose rows may be updated (e.g. ``candidates``,
  ``inboxes``).
* :class:`Immutable` adds only ``created_at``. Use this for append-only
  tables (:class:`ProcessingAttempt`, :class:`ImportCommand`,
  :class:`WalletAttempt`, :class:`ReviewDecision`, :class:`AuditEvent`).
  The absence of ``updated_at`` is a schema-level signal of the
  immutability invariant called out in the DeepSeek V4 review (section 9.2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Project-wide declarative base.

    All Wallet V2 models inherit from this class so they share a single
    :class:`~sqlalchemy.MetaData` instance that Alembic autogeneration and
    the hand-written migration both target.
    """

    metadata: Any  # populated by SQLAlchemy; declared here for type checkers


class Timestamped:
    """Mixin adding ``created_at`` and ``updated_at`` columns.

    ``updated_at`` is server-side refreshed on every UPDATE via SQLAlchemy's
    ``onupdate`` hook. Tables that should be immutable use :class:`Immutable`
    instead; the absence of ``updated_at`` is the immutability signal.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class Immutable:
    """Mixin adding only ``created_at``.

    Append-only tables (attempts, import commands, wallet attempts, review
    decisions, audit events) use this mixin. They have no ``updated_at``
    column; the absence is intentional and is asserted by the test suite.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

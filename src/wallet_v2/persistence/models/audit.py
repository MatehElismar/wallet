"""Cross-cutting audit events.

:class:`AuditEvent` is an append-only log of every workflow transition.
The DeepSeek V4 review (section 9.2) requires that audit rows are
immutable; this table therefore uses :class:`Immutable` (no
``updated_at``).

The ``entity_kind`` / ``entity_id`` pair is a soft FK — no
database-level constraint couples audit events to a specific table, so the
audit log survives even if a referenced row is purged under a retention
policy.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from wallet_v2.domain.enums import AuditEventKind
from wallet_v2.persistence.base import Base, Immutable
from wallet_v2.persistence.types import JSONB


class AuditEvent(Base, Immutable):
    """An immutable audit log row.

    Attributes:
        entity_kind: the kind of entity the event concerns (e.g.
            ``"source_message"``, ``"attempt"``, ``"import_command"``).
        entity_id: the UUID of the entity. Soft FK — not constrained.
        event_kind: the :class:`AuditEventKind` categorizing the event.
        payload: optional JSONB detail (before/after state, transition
            metadata).
        occurred_at: when the event happened (timezone-aware).
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "ix_audit_events_entity",
            "entity_kind",
            "entity_id",
            "occurred_at",
        ),
        Index("ix_audit_events_event_kind", "event_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_kind: Mapped[AuditEventKind] = mapped_column(
        String(48), nullable=False
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

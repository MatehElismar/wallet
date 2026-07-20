"""Durable notification outbox for idempotent, retryable push delivery.

Every notification intent is inserted exactly once per idempotency key. The
worker claims records, delivers them through the push provider, and records
the outcome. Delivery is never coupled to a domain transaction — the outbox
is the authoritative record of notification intent.

A stale subscription disables the outbox record without retry loops. The
subscription endpoint is demoted to ``disabled`` synchronously.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from wallet_v2.persistence.base import Base, Timestamped
from wallet_v2.persistence.types import JSONB


class NotificationOutbox(Base, Timestamped):
    """One durable notification intent queued for push delivery.

    The ``idempotency_key`` is globally unique and ensures that the same
    domain event (e.g. a statement batch approval) only creates one outbox
    record even if the event is processed multiple times.

    Delivery is retryable: a ``failed`` record is claimed again on the next
    worker cycle, with each attempt incrementing ``attempt_count``. The
    ``max_attempts`` column is a static guard in the schema; the worker also
    enforces the same limit at the application layer.

    When the provider indicates the subscription is stale, the record is
    marked ``stale`` and the subscription is disabled. No further delivery
    is attempted for a stale record.
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            "subscription_id",
            name="uq_notification_outbox_idempotency_key_subscription",
        ),
        Index(
            "ix_notification_outbox_pending",
            "status",
            "created_at",
            postgresql_using="btree",
        ),
        Index(
            "ix_notification_outbox_subscription",
            "subscription_id",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'delivered', 'failed', 'stale')",
            name="ck_notification_outbox_status",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_notification_outbox_attempt_count"
        ),
        CheckConstraint(
            "max_attempts >= 1", name="ck_notification_outbox_max_attempts"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("push_subscriptions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    intent_kind: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    entity_kind: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    last_error_kind: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    last_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

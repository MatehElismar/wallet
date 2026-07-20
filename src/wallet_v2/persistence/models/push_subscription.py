"""Browser/device push notification subscriptions.

A subscription is mutable — it can be created, re-registered (p256dh / auth
rotation), and disabled when the provider signals the endpoint is stale. The
lifecycle is governed by :class:`SubscriptionStatus`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from wallet_v2.persistence.base import Base, Timestamped


class PushSubscription(Base, Timestamped):
    """A browser push subscription registered by the operator's device."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        CheckConstraint(
            "status IN ('active', 'disabled', 'expired')",
            name="ck_push_subscriptions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False)
    keys_p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    keys_auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

"""Idempotent notification outbox service.

Encapsulates the rules for inserting one NotificationOutbox record per
unique domain event and for selecting active subscriptions.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from wallet_v2.domain.notifications import NotificationIntent
from wallet_v2.persistence.models.notification_outbox import NotificationOutbox
from wallet_v2.persistence.models.push_subscription import PushSubscription


class OutboxService:
    """Enqueues notification intents as idempotent outbox records."""

    def __init__(self, session: Session):
        self._session = session

    def enqueue(self, intent: NotificationIntent) -> NotificationOutbox | None:
        """Insert one outbox record per active subscription, if not already present.

        Idempotency is scoped per-subscription, so each active subscription gets
        at most one record per unique idempotency key.

        Returns the created record (the last one if multiple subscriptions exist)
        or ``None`` if no active subscriptions are available.
        """
        active_subs = self._active_subscriptions()
        if not active_subs:
            return None

        created: NotificationOutbox | None = None
        for sub in active_subs:
            existing = self._session.execute(
                select(NotificationOutbox.id).where(
                    NotificationOutbox.idempotency_key == intent.idempotency_key,
                    NotificationOutbox.subscription_id == sub.id,
                )
            ).first()
            if existing is not None:
                continue

            record = NotificationOutbox(
                id=uuid.uuid4(),
                idempotency_key=intent.idempotency_key,
                subscription_id=sub.id,
                intent_kind=intent.kind,
                title=intent.title,
                body=intent.body,
                entity_kind=intent.entity_kind,
                entity_id=intent.entity_id,
                payload_metadata=intent.metadata if intent.metadata else None,
            )
            self._session.add(record)
            created = record

        self._session.flush()
        return created

    def _active_subscriptions(self) -> Sequence[PushSubscription]:
        return (
            self._session.execute(
                select(PushSubscription).where(
                    PushSubscription.status == "active"
                )
            )
            .scalars()
            .all()
        )

    def disable_subscription(
        self, subscription_id: uuid.UUID, *, reason: str
    ) -> PushSubscription | None:
        """Synchronously disable a stale subscription."""
        sub = self._session.get(PushSubscription, subscription_id)
        if sub is None or sub.status != "active":
            return None
        from datetime import datetime, timezone

        sub.status = "disabled"
        sub.disabled_at = datetime.now(timezone.utc)
        sub.disabled_reason = reason
        self._session.flush()
        return sub

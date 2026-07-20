"""Outbox worker: claim, deliver, retry pending notification records.

The worker operates in a polling loop. Each cycle claims up to
``batch_size`` pending records, delivers them through the push provider,
and records the outcome. Delivery is bounded by ``max_attempts`` per record
and a deterministic injectable ``now`` callable for testability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from wallet_v2.application.contracts import PushMessage, PushProvider
from wallet_v2.application.outbox import OutboxService
from wallet_v2.persistence.models.notification_outbox import NotificationOutbox
from wallet_v2.persistence.models.push_subscription import PushSubscription


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class WorkerStats:
    """Summary of one delivery cycle."""

    claimed: int
    delivered: int
    failed: int
    stale: int
    skipped: int


class OutboxWorker:
    """Claims pending outbox records, delivers them, and records outcomes."""

    def __init__(
        self,
        session: Session,
        provider: PushProvider,
        *,
        now: Callable[[], datetime] = _utcnow,
        batch_size: int = 10,
    ):
        self._session = session
        self._provider = provider
        self._now = now
        self._batch_size = batch_size

    def run_cycle(self) -> WorkerStats:
        """Claim and deliver one batch of pending outbox records.

        Returns summary statistics for the cycle.
        """
        records = self._claim_pending()
        if not records:
            return WorkerStats(
                claimed=0, delivered=0, failed=0, stale=0, skipped=0
            )

        return self._deliver_all(records)

    def _claim_pending(self) -> Sequence[NotificationOutbox]:
        now = self._now()
        cutoff = str(now)

        stmt = (
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status.in_(["pending", "failed"]),
                NotificationOutbox.attempt_count < NotificationOutbox.max_attempts,
            )
            .order_by(NotificationOutbox.created_at.asc())
            .limit(self._batch_size)
            .with_for_update(skip_locked=True)
        )

        records = self._session.execute(stmt).scalars().all()

        if records:
            ids = [r.id for r in records]
            self._session.execute(
                update(NotificationOutbox)
                .where(NotificationOutbox.id.in_(ids))
                .values(status="claimed", claimed_at=now)
            )
            self._session.flush()

        return records

    def _deliver_all(
        self, records: Sequence[NotificationOutbox]
    ) -> WorkerStats:
        outbox = OutboxService(self._session)
        now = self._now()
        stats = WorkerStats(
            claimed=len(records), delivered=0, failed=0, stale=0, skipped=0
        )

        for record in records:
            sub = self._get_subscription(record.subscription_id)
            if sub is None or sub.status != "active":
                self._mark_skipped(record, now)
                stats = WorkerStats(
                    claimed=stats.claimed,
                    delivered=stats.delivered,
                    failed=stats.failed,
                    stale=stats.stale,
                    skipped=stats.skipped + 1,
                )
                continue

            message = PushMessage(
                endpoint=sub.endpoint,
                keys_p256dh=sub.keys_p256dh,
                keys_auth=sub.keys_auth,
                title=record.title,
                body=record.body,
                metadata=record.payload_metadata,
            )

            try:
                result = self._provider.send(message)
            except Exception:
                self._mark_failed(
                    record, now, error_kind="provider_unavailable"
                )
                stats = WorkerStats(
                    claimed=stats.claimed,
                    delivered=stats.delivered,
                    failed=stats.failed + 1,
                    stale=stats.stale,
                    skipped=stats.skipped,
                )
                continue

            if result.subscription_stale:
                outbox.disable_subscription(
                    sub.id, reason="stale_subscription_response"
                )
                self._mark_stale(record, now)
                self._mark_pending_stale(sub.id, now)
                stats = WorkerStats(
                    claimed=stats.claimed,
                    delivered=stats.delivered,
                    failed=stats.failed,
                    stale=stats.stale + 1,
                    skipped=stats.skipped,
                )
            elif result.success:
                self._mark_delivered(
                    record, now, provider_message_id=result.provider_message_id
                )
                stats = WorkerStats(
                    claimed=stats.claimed,
                    delivered=stats.delivered + 1,
                    failed=stats.failed,
                    stale=stats.stale,
                    skipped=stats.skipped,
                )
            else:
                self._mark_failed(
                    record,
                    now,
                    error_kind=result.error_kind,
                    error_message=result.error_message,
                )
                stats = WorkerStats(
                    claimed=stats.claimed,
                    delivered=stats.delivered,
                    failed=stats.failed + 1,
                    stale=stats.stale,
                    skipped=stats.skipped,
                )

        self._session.flush()
        return stats

    def _get_subscription(
        self, subscription_id: object
    ) -> PushSubscription | None:
        return self._session.get(PushSubscription, subscription_id)

    def _mark_delivered(
        self,
        record: NotificationOutbox,
        now: datetime,
        *,
        provider_message_id: str | None = None,
    ) -> None:
        record.status = "delivered"
        record.delivered_at = now
        record.attempt_count += 1
        if provider_message_id:
            record.provider_message_id = provider_message_id

    def _mark_failed(
        self,
        record: NotificationOutbox,
        now: datetime,
        *,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> None:
        record.status = "failed"
        record.attempt_count += 1
        if error_kind:
            record.last_error_kind = error_kind
        if error_message:
            record.last_error_message = error_message

    def _mark_stale(
        self,
        record: NotificationOutbox,
        now: datetime,
    ) -> None:
        record.status = "stale"
        record.attempt_count += 1
        record.last_error_kind = "stale_subscription"
        record.last_error_message = (
            "Subscription endpoint returned stale; subscription disabled"
        )

    def _mark_skipped(
        self,
        record: NotificationOutbox,
        now: datetime,
    ) -> None:
        record.status = "stale"
        record.attempt_count += 1
        record.last_error_kind = "inactive_subscription"
        record.last_error_message = (
            "Subscription is not active; record skipped"
        )

    def _mark_pending_stale(
        self, subscription_id: object, now: datetime
    ) -> None:
        """Mark all pending/claimed records for a stale subscription as stale."""
        self._session.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.subscription_id == subscription_id,
                NotificationOutbox.status.in_(["pending", "claimed"]),
            )
            .values(status="stale")
        )

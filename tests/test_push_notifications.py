"""Hermetic tests for push notification persistence, delivery, API, and workflow integration.

All tests run against in-memory SQLite with no network access. The push
provider is a controllable stub. Push is disabled by default; API tests
enable it explicitly when testing subscription endpoints.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from wallet_v2.api.app import create_test_app
from wallet_v2.application.contracts import (
    PushDeliveryResult,
    PushMessage,
    PushProvider,
)
from wallet_v2.application.outbox import OutboxService
from wallet_v2.application.service import WalletWorkflow
from wallet_v2.application.worker import OutboxWorker
from wallet_v2.config import PushSettings
from wallet_v2.domain.enums import IntegrationMode, NotificationIntentKind
from wallet_v2.domain.notifications import (
    DeliveryResult,
    NotificationIntent,
    PushSubscriptionData,
)
from wallet_v2.persistence.base import Base
from wallet_v2.persistence.models import (
    AuditEvent,
    NotificationOutbox,
    PushSubscription,
)
from wallet_v2.application.contracts import (
    ExtractedStatement,
    ExtractedTransaction,
    ExtractionResult,
    MailboxMessage,
)


def _utcnow() -> datetime:
    return datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(*, kind: str = "review_pending", entity_id: str | None = None) -> NotificationIntent:
    return NotificationIntent(
        idempotency_key=f"test:{kind}:{entity_id or uuid.uuid4()}",
        kind=kind,
        title="Test Notification",
        body="This is a test.",
        entity_kind="test",
        entity_id=entity_id or str(uuid.uuid4()),
        metadata={"source": "test"},
    )


def _active_sub(session: Any) -> PushSubscription:
    sub = PushSubscription(
        id=uuid.uuid4(),
        endpoint="https://push.test/endpoint-1",
        keys_p256dh="p256dh_key_1",
        keys_auth="auth_key_1",
        user_agent="test-agent/1.0",
    )
    session.add(sub)
    session.flush()
    return sub


# ---------------------------------------------------------------------------
# OutboxService
# ---------------------------------------------------------------------------

class TestOutboxService:

    def test_enqueue_creates_record(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        intent = _make_intent(entity_id=str(sub.id))
        result = outbox.enqueue(intent)
        assert result is not None
        assert result.idempotency_key == intent.idempotency_key
        assert result.subscription_id == sub.id
        assert result.status == "pending"

    def test_enqueue_idempotent(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        intent = _make_intent(entity_id=str(sub.id))
        first = outbox.enqueue(intent)
        assert first is not None
        second = outbox.enqueue(intent)
        assert second is None

    def test_enqueue_no_active_subscriptions(self, session: Any) -> None:
        outbox = OutboxService(session)
        intent = _make_intent()
        result = outbox.enqueue(intent)
        assert result is None

    def test_enqueue_disabled_subscription_skipped(self, session: Any) -> None:
        sub = _active_sub(session)
        sub.status = "disabled"
        session.flush()
        outbox = OutboxService(session)
        intent = _make_intent(entity_id=str(sub.id))
        result = outbox.enqueue(intent)
        assert result is None

    def test_enqueue_creates_record_per_subscription(self, session: Any) -> None:
        sub1 = _active_sub(session)
        sub2 = PushSubscription(
            id=uuid.uuid4(),
            endpoint="https://push.test/endpoint-2",
            keys_p256dh="p256dh_key_2",
            keys_auth="auth_key_2",
        )
        session.add(sub2)
        session.flush()
        outbox = OutboxService(session)
        intent = _make_intent(entity_id="multi-sub")
        outbox.enqueue(intent)
        records = session.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.idempotency_key == intent.idempotency_key
            )
        ).scalars().all()
        assert len(records) == 2
        sub_ids = {r.subscription_id for r in records}
        assert sub_ids == {sub1.id, sub2.id}

    def test_disable_subscription(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        result = outbox.disable_subscription(sub.id, reason="provider_stale")
        assert result is not None
        assert result.status == "disabled"
        assert result.disabled_reason == "provider_stale"
        session.expire_all()
        reloaded = session.get(PushSubscription, sub.id)
        assert reloaded.status == "disabled"

    def test_disable_already_disabled(self, session: Any) -> None:
        sub = _active_sub(session)
        sub.status = "disabled"
        session.flush()
        outbox = OutboxService(session)
        result = outbox.disable_subscription(sub.id, reason="again")
        assert result is None


# ---------------------------------------------------------------------------
# OutboxWorker
# ---------------------------------------------------------------------------

class _StubProvider:
    def __init__(self, outcomes: list[PushDeliveryResult] | None = None) -> None:
        self._outcomes = list(outcomes or [])
        self.calls: list[PushMessage] = []

    def send(self, message: PushMessage) -> PushDeliveryResult:
        self.calls.append(message)
        if self._outcomes:
            return self._outcomes.pop(0)
        return PushDeliveryResult(success=True, provider_message_id="msg-default")


class TestOutboxWorker:

    def test_run_cycle_empty(self, session: Any) -> None:
        worker = OutboxWorker(session, provider=_StubProvider(), now=_utcnow)
        stats = worker.run_cycle()
        assert stats.claimed == 0
        assert stats.delivered == 0

    def test_run_cycle_delivers_pending(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        outbox.enqueue(_make_intent(entity_id=str(sub.id)))
        session.commit()

        provider = _StubProvider()
        worker = OutboxWorker(session, provider=provider, now=_utcnow)
        stats = worker.run_cycle()
        assert stats.claimed == 1
        assert stats.delivered == 1
        assert stats.failed == 0
        assert stats.stale == 0

        record = session.execute(
            select(NotificationOutbox)
        ).scalars().one()
        assert record.status == "delivered"
        from datetime import timezone
        assert record.delivered_at.replace(tzinfo=timezone.utc) == _utcnow()
        assert record.provider_message_id == "msg-default"

    def test_run_cycle_retries_failed(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        outbox.enqueue(_make_intent(entity_id=str(sub.id)))
        session.commit()
        record = session.execute(
            select(NotificationOutbox)
        ).scalars().one()
        record.status = "failed"
        record.attempt_count = 1
        session.flush()

        provider = _StubProvider()
        worker = OutboxWorker(session, provider=provider, now=_utcnow)
        stats = worker.run_cycle()
        assert stats.claimed == 1
        assert stats.delivered == 1

        session.expire_all()
        record = session.execute(
            select(NotificationOutbox)
        ).scalars().one()
        assert record.status == "delivered"
        assert record.attempt_count == 2

    def test_run_cycle_stale_subscription(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        outbox.enqueue(_make_intent(entity_id=str(sub.id)))
        session.commit()

        provider = _StubProvider(
            outcomes=[PushDeliveryResult(success=False, subscription_stale=True)]
        )
        worker = OutboxWorker(session, provider=provider, now=_utcnow)
        stats = worker.run_cycle()
        assert stats.claimed == 1
        assert stats.stale == 1
        assert stats.delivered == 0

        session.expire_all()
        record = session.execute(
            select(NotificationOutbox)
        ).scalars().one()
        assert record.status == "stale"
        assert record.last_error_kind == "stale_subscription"

        sub_reloaded = session.get(PushSubscription, sub.id)
        assert sub_reloaded.status == "disabled"
        assert sub_reloaded.disabled_reason == "stale_subscription_response"

    def test_run_cycle_inactive_subscription_skipped(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        intent = _make_intent(entity_id=str(sub.id))
        outbox.enqueue(intent)
        session.flush()
        sub.status = "disabled"
        session.commit()

        provider = _StubProvider()
        worker = OutboxWorker(session, provider=provider, now=_utcnow)
        stats = worker.run_cycle()
        assert stats.claimed == 1
        assert stats.skipped == 1
        assert stats.delivered == 0

        session.expire_all()
        record = session.execute(
            select(NotificationOutbox)
        ).scalars().one()
        assert record.status == "stale"
        assert record.last_error_kind == "inactive_subscription"

    def test_run_cycle_provider_unavailable(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        outbox.enqueue(_make_intent(entity_id=str(sub.id)))
        session.commit()

        class _FailingProvider:
            def send(self, message: PushMessage) -> PushDeliveryResult:
                raise RuntimeError("connection refused")

        worker = OutboxWorker(session, provider=_FailingProvider(), now=_utcnow)
        stats = worker.run_cycle()
        assert stats.claimed == 1
        assert stats.failed == 1

        session.expire_all()
        record = session.execute(
            select(NotificationOutbox)
        ).scalars().one()
        assert record.status == "failed"
        assert record.last_error_kind == "provider_unavailable"

    def test_run_cycle_exhausts_max_attempts(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        outbox.enqueue(_make_intent(entity_id=str(sub.id)))
        session.commit()
        record = session.execute(
            select(NotificationOutbox)
        ).scalars().one()
        record.attempt_count = 5
        record.max_attempts = 5
        record.status = "failed"
        session.flush()

        provider = _StubProvider()
        worker = OutboxWorker(session, provider=provider, now=_utcnow)
        stats = worker.run_cycle()
        assert stats.claimed == 0

    def test_run_cycle_marks_pending_stale(self, session: Any) -> None:
        sub = _active_sub(session)
        outbox = OutboxService(session)
        outbox.enqueue(_make_intent(entity_id=str(sub.id)))
        session.commit()
        # create a second pending record for the same sub
        other = NotificationOutbox(
            id=uuid.uuid4(),
            idempotency_key="other-intent",
            subscription_id=sub.id,
            intent_kind="review_pending",
            title="Other",
            body="Other",
            entity_kind="test",
            entity_id="other",
        )
        session.add(other)
        session.flush()

        provider = _StubProvider(
            outcomes=[PushDeliveryResult(success=False, subscription_stale=True)]
        )
        worker = OutboxWorker(session, provider=provider, now=_utcnow)
        # Both pending records are claimed; one delivery attempt marks sub stale,
        # the second record is skipped because sub is now disabled.
        stats = worker.run_cycle()
        assert stats.claimed == 2
        assert stats.stale == 1
        assert stats.skipped == 1

        # the other pending record should also be marked stale
        session.expire_all()
        other_reloaded = session.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.idempotency_key == "other-intent"
            )
        ).scalars().one()
        assert other_reloaded.status == "stale"


# ---------------------------------------------------------------------------
# Push API
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    app = create_test_app()
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


def _enable_push(app: Any) -> None:
    """Enable push in dry-run mode on the test app."""
    app.state.settings = app.state.settings.with_overrides(
        push=PushSettings(
            mode=IntegrationMode.DRY_RUN,
            public_key="BC1x_test_public_key_for_testing",
            private_key="test_private_key",
            subject="mailto:test@test.local",
        )
    )


class TestPushConfig:

    def test_default_disabled(self, client: TestClient) -> None:
        response = client.get("/push/config")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert data["public_key"] is None

    def test_enabled_returns_public_key(self, client: TestClient) -> None:
        _enable_push(client.app)
        response = client.get("/push/config")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["public_key"] == "BC1x_test_public_key_for_testing"


class TestRegisterSubscription:

    def test_disabled_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/push/subscriptions",
            json={
                "endpoint": "https://push.test/ep",
                "keys_p256dh": "key_p256dh",
                "keys_auth": "key_auth",
            },
        )
        assert response.status_code == 400
        assert "disabled" in response.json()["detail"].lower()

    def test_register_new(self, client: TestClient) -> None:
        _enable_push(client.app)
        response = client.post(
            "/push/subscriptions",
            json={
                "endpoint": "https://push.test/ep-new",
                "keys_p256dh": "key_p256dh",
                "keys_auth": "key_auth",
                "user_agent": "test-browser/1.0",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "active"
        assert uuid.UUID(data["subscription_id"])

    def test_register_re_registers_existing(self, client: TestClient) -> None:
        _enable_push(client.app)
        # first registration
        response = client.post(
            "/push/subscriptions",
            json={
                "endpoint": "https://push.test/ep-rereg",
                "keys_p256dh": "key_v1",
                "keys_auth": "auth_v1",
            },
        )
        assert response.status_code == 201
        sub_id = response.json()["subscription_id"]

        # re-registration with rotated keys
        response = client.post(
            "/push/subscriptions",
            json={
                "endpoint": "https://push.test/ep-rereg",
                "keys_p256dh": "key_v2",
                "keys_auth": "auth_v2",
            },
        )
        assert response.status_code == 201
        assert response.json()["subscription_id"] == sub_id

        factory = client.app.state.session_factory
        with factory() as session:
            sub = session.get(PushSubscription, uuid.UUID(sub_id))
            assert sub.keys_p256dh == "key_v2"
            assert sub.keys_auth == "auth_v2"

    def test_register_reactivates_disabled(self, client: TestClient) -> None:
        _enable_push(client.app)
        factory = client.app.state.session_factory
        with factory() as session:
            sub = PushSubscription(
                id=uuid.uuid4(),
                endpoint="https://push.test/ep-reactivate",
                keys_p256dh="key_orig",
                keys_auth="auth_orig",
                status="disabled",
                disabled_at=_utcnow(),
                disabled_reason="test_disable",
            )
            session.add(sub)
            session.commit()
            sub_id = str(sub.id)

        response = client.post(
            "/push/subscriptions",
            json={
                "endpoint": "https://push.test/ep-reactivate",
                "keys_p256dh": "key_new",
                "keys_auth": "auth_new",
            },
        )
        assert response.status_code == 201
        assert response.json()["subscription_id"] == sub_id

        with factory() as session:
            sub = session.get(PushSubscription, uuid.UUID(sub_id))
            assert sub.status == "active"
            assert sub.disabled_at is None
            assert sub.disabled_reason is None


class TestDisableSubscription:

    def test_disabled_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/push/subscriptions/00000000-0000-0000-0000-000000000000/disable",
        )
        assert response.status_code == 400

    def test_disable_active(self, client: TestClient) -> None:
        _enable_push(client.app)
        factory = client.app.state.session_factory
        with factory() as session:
            sub = _active_sub(session)
            session.commit()
            sub_id = str(sub.id)

        response = client.post(f"/push/subscriptions/{sub_id}/disable")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disabled"

        with factory() as session:
            sub = session.get(PushSubscription, uuid.UUID(sub_id))
            assert sub.status == "disabled"
            assert sub.disabled_reason == "operator_disabled"

    def test_disable_not_found(self, client: TestClient) -> None:
        _enable_push(client.app)
        response = client.post(
            "/push/subscriptions/00000000-0000-0000-0000-000000000000/disable",
        )
        assert response.status_code == 404

    def test_disable_already_disabled(self, client: TestClient) -> None:
        _enable_push(client.app)
        factory = client.app.state.session_factory
        with factory() as session:
            sub = _active_sub(session)
            sub.status = "disabled"
            session.commit()
            sub_id = str(sub.id)

        response = client.post(f"/push/subscriptions/{sub_id}/disable")
        assert response.status_code == 409


class TestListSubscriptions:

    def test_empty(self, client: TestClient) -> None:
        _enable_push(client.app)
        response = client.get("/push/subscriptions")
        assert response.status_code == 200
        data = response.json()
        assert data["active_count"] == 0
        assert data["disabled_count"] == 0
        assert data["subscriptions"] == []

    def test_lists_subscriptions(self, client: TestClient) -> None:
        _enable_push(client.app)
        factory = client.app.state.session_factory
        with factory() as session:
            sub1 = _active_sub(session)
            sub2 = PushSubscription(
                id=uuid.uuid4(),
                endpoint="https://push.test/ep-disabled",
                keys_p256dh="k2",
                keys_auth="a2",
                status="disabled",
            )
            session.add(sub2)
            session.commit()

        response = client.get("/push/subscriptions")
        assert response.status_code == 200
        data = response.json()
        assert data["active_count"] == 1
        assert data["disabled_count"] == 1
        assert len(data["subscriptions"]) == 2


# ---------------------------------------------------------------------------
# Workflow integration — notification emission from WalletWorkflow
# ---------------------------------------------------------------------------

class TestWorkflowNotificationEmission:

    def test_emit_review_pending_on_candidate_creation(self, session: Any) -> None:
        outbox = OutboxService(session)
        _active_sub(session)
        session.commit()

        workflow = WalletWorkflow(session, now=_utcnow, outbox_service=outbox)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="push-test")

        message = MailboxMessage(
            provider="imap", account_fingerprint="f" * 64, folder="INBOX",
            uid_validity=1, message_uid=1,
            sender="noreply@test.local", recipient="wallet@test.local",
            subject="Notification", message_id_header="<notif-1@t>",
            received_at=_utcnow(), body_text="Test.",
        )

        class _NotifExtractor:
            def extract(self, _msg: object) -> ExtractionResult:
                return ExtractionResult(
                    is_transaction=True,
                    transaction=ExtractedTransaction(
                        direction="debit", amount_minor=1000, currency="USD",
                        merchant="Test Merchant",
                    ),
                    raw_response={},
                    structured_output={},
                    model_id="test",
                )

        source, candidates, tasks = workflow.ingest_and_extract(
            run=run, message=message, extractor=_NotifExtractor()
        )
        session.flush()

        outbox_records = session.execute(
            select(NotificationOutbox)
        ).scalars().all()
        assert len(outbox_records) == 1
        assert outbox_records[0].intent_kind == NotificationIntentKind.REVIEW_PENDING
        assert outbox_records[0].entity_id == str(source.id)
        assert outbox_records[0].title == "Review Pending"

    def test_default_outbox_service_emits_notifications(self, session: Any) -> None:
        # The workflow owns an outbox service by default so normal production
        # construction cannot silently drop notification intents.
        _active_sub(session)
        session.commit()

        workflow = WalletWorkflow(session, now=_utcnow)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="no-push")

        message = MailboxMessage(
            provider="imap", account_fingerprint="f" * 64, folder="INBOX",
            uid_validity=1, message_uid=2,
            sender="noreply@test.local", recipient="wallet@test.local",
            subject="Notification", message_id_header="<notif-2@t>",
            received_at=_utcnow(), body_text="Test.",
        )

        class _NotifExtractor:
            def extract(self, _msg: object) -> ExtractionResult:
                return ExtractionResult(
                    is_transaction=True,
                    transaction=ExtractedTransaction(
                        direction="debit", amount_minor=1000, currency="USD",
                        merchant="Test Merchant",
                    ),
                    raw_response={},
                    structured_output={},
                    model_id="test",
                )

        workflow.ingest_and_extract(
            run=run, message=message, extractor=_NotifExtractor()
        )
        session.flush()

        outbox_records = session.execute(
            select(NotificationOutbox)
        ).scalars().all()
        assert len(outbox_records) == 1

    def test_emit_no_notification_without_active_subscriptions(self, session: Any) -> None:
        # No active subscriptions → no outbox records
        outbox = OutboxService(session)
        session.commit()

        workflow = WalletWorkflow(session, now=_utcnow, outbox_service=outbox)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="no-sub")

        message = MailboxMessage(
            provider="imap", account_fingerprint="f" * 64, folder="INBOX",
            uid_validity=1, message_uid=3,
            sender="noreply@test.local", recipient="wallet@test.local",
            subject="Notification", message_id_header="<notif-3@t>",
            received_at=_utcnow(), body_text="Test.",
        )

        class _NotifExtractor:
            def extract(self, _msg: object) -> ExtractionResult:
                return ExtractionResult(
                    is_transaction=True,
                    transaction=ExtractedTransaction(
                        direction="debit", amount_minor=1000, currency="USD",
                        merchant="Test Merchant",
                    ),
                    raw_response={},
                    structured_output={},
                    model_id="test",
                )

        workflow.ingest_and_extract(
            run=run, message=message, extractor=_NotifExtractor()
        )
        session.flush()

        outbox_records = session.execute(
            select(NotificationOutbox)
        ).scalars().all()
        assert len(outbox_records) == 0

    def test_emit_run_failed_on_finish_failure(self, session: Any) -> None:
        outbox = OutboxService(session)
        _active_sub(session)
        session.commit()

        workflow = WalletWorkflow(session, now=_utcnow, outbox_service=outbox)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="manual", label="fail-test")
        workflow.finish_run(run, outcome="failed", error="Something went wrong")
        session.flush()

        outbox_records = session.execute(
            select(NotificationOutbox)
        ).scalars().all()
        assert len(outbox_records) == 1
        assert outbox_records[0].intent_kind == NotificationIntentKind.RUN_FAILED

    def test_no_emit_on_successful_finish(self, session: Any) -> None:
        outbox = OutboxService(session)
        _active_sub(session)
        session.commit()

        workflow = WalletWorkflow(session, now=_utcnow, outbox_service=outbox)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="success")
        workflow.finish_run(run, outcome="succeeded")
        session.flush()

        outbox_records = session.execute(
            select(NotificationOutbox)
        ).scalars().all()
        assert len(outbox_records) == 0

    def test_emit_batch_approved(self, session: Any) -> None:
        outbox = OutboxService(session)
        _active_sub(session)
        session.commit()

        workflow = WalletWorkflow(session, now=_utcnow, outbox_service=outbox)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="batch-test")

        message = MailboxMessage(
            provider="imap", account_fingerprint="b" * 64, folder="INBOX",
            uid_validity=1, message_uid=10,
            sender="alerts@test.local", recipient="wallet@test.local",
            subject="Statement", message_id_header="<stmt-10@t>",
            received_at=_utcnow(), body_text="Statement text.",
        )

        class _StmtExtractor:
            def extract(self, _msg: object) -> ExtractionResult:
                return ExtractionResult(
                    is_transaction=True,
                    transaction=ExtractedTransaction(
                        direction="debit", amount_minor=5000, currency="USD",
                        merchant="Shop",
                    ),
                    transactions=(
                        ExtractedTransaction(direction="debit", amount_minor=5000, currency="USD", merchant="Shop"),
                    ),
                    raw_response={},
                    structured_output={},
                    model_id="test",
                    document_kind="statement",
                    statement=ExtractedStatement(
                        issuer="TestBank", account_reference="acc-1",
                        period_start=datetime(2026, 7, 1).date(),
                        period_end=datetime(2026, 7, 15).date(),
                    ),
                )

        workflow.ingest_and_extract(run=run, message=message, extractor=_StmtExtractor())
        session.flush()

        from wallet_v2.persistence.models import StatementReviewBatch
        batch = session.scalars(select(StatementReviewBatch)).one()
        workflow.approve_statement_batch(
            run=run, batch=batch, reviewer_id="test-reviewer",
        )
        session.flush()

        outbox_records = session.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.intent_kind == NotificationIntentKind.BATCH_APPROVED
            )
        ).scalars().all()
        assert len(outbox_records) == 1
        assert outbox_records[0].entity_id == str(batch.id)

    def test_emit_idempotent_same_event(self, session: Any) -> None:
        outbox = OutboxService(session)
        _active_sub(session)
        session.commit()

        workflow = WalletWorkflow(session, now=_utcnow, outbox_service=outbox)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="manual", label="idempotent")

        # Same failure outcome twice
        workflow.finish_run(run, outcome="failed", error="Err")

        run2 = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="manual", label="idempotent-2")
        workflow.finish_run(run2, outcome="failed", error="Err")
        session.flush()

        outbox_records = session.execute(
            select(NotificationOutbox)
        ).scalars().all()
        # Each run has a different entity_id so they're different idempotency keys
        assert len(outbox_records) == 2


# ---------------------------------------------------------------------------
# Domain value objects
# ---------------------------------------------------------------------------

class TestDomainObjects:

    def test_notification_intent_defaults(self) -> None:
        intent = NotificationIntent(
            idempotency_key="k1", kind="test", title="T", body="B",
            entity_kind="e", entity_id="1",
        )
        assert intent.metadata == {}

    def test_push_subscription_data(self) -> None:
        data = PushSubscriptionData(
            endpoint="https://ep", keys_p256dh="pk", keys_auth="ak",
        )
        assert data.user_agent is None

    def test_delivery_result_defaults(self) -> None:
        result = DeliveryResult(success=True)
        assert result.provider_message_id is None
        assert result.error_kind is None
        assert result.error_message is None
        assert result.subscription_disabled is False

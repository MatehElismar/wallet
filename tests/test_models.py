"""Schema and constraint tests for the Wallet V2 persistence layer.

These tests do not require a live PostgreSQL. They build an in-memory
SQLite engine from the ORM metadata and exercise:

* Source identity: the inbox unique triple
  ``(provider, account_fingerprint, folder)`` and the source-message
  unique triple ``(inbox_id, uid_validity, message_uid)``.
* Idempotency: ``processing_attempts.idempotency_key`` and
  ``import_commands.idempotency_key`` are unique; duplicate inserts raise
  ``IntegrityError``.
* Immutability signal: the append-only tables have no ``updated_at``
  column.
* Import-command state machine: ``unknown`` is a representable status
  and a persisted row round-trips with it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wallet_v2.domain.enums import (
    AttemptStatus,
    CandidateStatus,
    ImportCommandStatus,
    MailboxSourceStatus,
    SourceMessageStatus,
    TransactionDirection,
)
from wallet_v2.persistence.models import (
    AuditEvent,
    ImportCommand,
    Inbox,
    InboxCursorHistory,
    ProcessingAttempt,
    ReviewDecisionRecord,
    ReviewTask,
    SourceMessage,
    TransactionCandidate,
    WalletAttempt,
    WalletReceipt,
)


_IMMUTABLE_TABLES = (
    "processing_attempts",
    "review_decisions",
    "wallet_attempts",
    "audit_events",
    "inbox_cursor_history",
    "bank_statement_lines",
    "transaction_observations",
    "financial_events",
)


_TIMESTAMPED_TABLES = (
    "inboxes",
    "source_messages",
    "message_content_metadata",
    "transaction_candidates",
    "review_tasks",
    "wallet_receipts",
    "financial_accounts",
    "bank_statements",
    "reconciliation_links",
    "statement_review_batches",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_inbox(session: Session, provider: str = "imap") -> Inbox:
    inbox = Inbox(
        provider=provider,
        account_fingerprint="a" * 64,
        folder="INBOX",
        status=MailboxSourceStatus.ACTIVE,
    )
    session.add(inbox)
    session.flush()
    return inbox


def _make_source_message(
    session: Session,
    inbox: Inbox,
    uid_validity: int = 1,
    message_uid: int = 1,
) -> SourceMessage:
    sm = SourceMessage(
        inbox_id=inbox.id,
        uid_validity=uid_validity,
        message_uid=message_uid,
        content_hash="0" * 64,
        status=SourceMessageStatus.RECEIVED,
        received_at=_utcnow(),
    )
    session.add(sm)
    session.flush()
    return sm


def _make_attempt(
    session: Session,
    source_message: SourceMessage,
    index: int = 1,
    idempotency_key: str | None = None,
) -> ProcessingAttempt:
    attempt = ProcessingAttempt(
        source_message_id=source_message.id,
        attempt_index=index,
        idempotency_key=idempotency_key
        or f"attempt-{source_message.id}-{index}",
        status=AttemptStatus.SUCCEEDED,
    )
    session.add(attempt)
    session.flush()
    return attempt


def _make_candidate(
    session: Session,
    source_message: SourceMessage,
    attempt: ProcessingAttempt,
    version: int = 1,
) -> TransactionCandidate:
    candidate = TransactionCandidate(
        source_message_id=source_message.id,
        attempt_id=attempt.id,
        candidate_version=version,
        status=CandidateStatus.PROPOSED,
        direction=TransactionDirection.DEBIT,
        amount_minor=1000,
        currency="USD",
    )
    session.add(candidate)
    session.flush()
    return candidate


def _make_import_command(
    session: Session,
    candidate: TransactionCandidate,
    idempotency_key: str | None = None,
    status: ImportCommandStatus = ImportCommandStatus.QUEUED,
) -> ImportCommand:
    cmd = ImportCommand(
        candidate_id=candidate.id,
        idempotency_key=idempotency_key or f"import-{candidate.id}",
        status=status,
        payload={"amount_minor": 1000, "currency": "USD"},
        issued_at=_utcnow(),
    )
    session.add(cmd)
    session.flush()
    return cmd


class TestTableRegistry:
    def test_all_twenty_tables_registered(self) -> None:
        from wallet_v2.persistence.base import Base

        expected = {
            "inboxes",
            "inbox_cursor_history",
            "source_messages",
            "message_content_metadata",
            "processing_attempts",
            "transaction_candidates",
            "review_tasks",
            "review_decisions",
            "import_commands",
            "wallet_attempts",
            "wallet_receipts",
            "audit_events",
            "execution_runs",
            "financial_accounts",
            "bank_statements",
            "bank_statement_lines",
            "transaction_observations",
            "reconciliation_links",
            "statement_review_batches",
            "financial_events",
        }
        assert set(Base.metadata.tables.keys()) == expected


class TestImmutabilitySignal:
    @pytest.mark.parametrize("table_name", _IMMUTABLE_TABLES)
    def test_immutable_table_has_no_updated_at(
        self, table_name: str
    ) -> None:
        from wallet_v2.persistence.base import Base

        table = Base.metadata.tables[table_name]
        assert "updated_at" not in table.columns, (
            f"{table_name} is supposed to be immutable but has an "
            "updated_at column"
        )
        assert "created_at" in table.columns

    @pytest.mark.parametrize("table_name", _TIMESTAMPED_TABLES)
    def test_timestamped_table_has_both_timestamps(
        self, table_name: str
    ) -> None:
        from wallet_v2.persistence.base import Base

        table = Base.metadata.tables[table_name]
        assert "created_at" in table.columns
        assert "updated_at" in table.columns


class TestSourceIdentityConstraint:
    def test_inbox_unique_on_provider_fingerprint_folder(
        self, session: Session
    ) -> None:
        inbox = _make_inbox(session)
        duplicate = Inbox(
            provider=inbox.provider,
            account_fingerprint=inbox.account_fingerprint,
            folder=inbox.folder,
            status=MailboxSourceStatus.ACTIVE,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_same_account_different_folders_allowed(
        self, session: Session
    ) -> None:
        inbox = _make_inbox(session)
        other_folder = Inbox(
            provider=inbox.provider,
            account_fingerprint=inbox.account_fingerprint,
            folder="Sent",
            status=MailboxSourceStatus.ACTIVE,
        )
        session.add(other_folder)
        session.flush()  # should not raise

    def test_source_message_unique_on_inbox_uidvalidity_uid(
        self, session: Session
    ) -> None:
        inbox = _make_inbox(session)
        _make_source_message(session, inbox, uid_validity=1, message_uid=10)
        dup = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=10,
            content_hash="0" * 64,
            status=SourceMessageStatus.RECEIVED,
            received_at=_utcnow(),
        )
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_different_uid_validity_allows_same_uid(
        self, session: Session
    ) -> None:
        inbox = _make_inbox(session)
        _make_source_message(session, inbox, uid_validity=1, message_uid=10)
        # Same UID, different validity epoch — legal, treated as distinct.
        _make_source_message(session, inbox, uid_validity=2, message_uid=10)
        session.flush()


class TestAttemptIdempotencyConstraint:
    def test_unique_idempotency_key(self, session: Session) -> None:
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        _make_attempt(session, sm, index=1, idempotency_key="dup-key")
        # Second attempt with the same key must be rejected.
        second = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=2,
            idempotency_key="dup-key",
            status=AttemptStatus.PENDING,
        )
        session.add(second)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_unique_source_message_attempt_index(self, session: Session) -> None:
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        _make_attempt(session, sm, index=1, idempotency_key="k1")
        # Same (source_message_id, attempt_index) must be rejected even
        # with a different idempotency_key.
        second = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=1,
            idempotency_key="k2",
            status=AttemptStatus.PENDING,
        )
        session.add(second)
        with pytest.raises(IntegrityError):
            session.flush()


class TestImportCommandIdempotencyConstraint:
    def test_unique_idempotency_key(self, session: Session) -> None:
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        attempt = _make_attempt(session, sm)
        candidate = _make_candidate(session, sm, attempt)
        _make_import_command(
            session, candidate, idempotency_key="shared-key-xxxxxxxx"
        )
        # Second command with the same key — even on a different candidate —
        # must be rejected.
        other_candidate = _make_candidate(
            session, sm, attempt, version=2
        )
        second = ImportCommand(
            candidate_id=other_candidate.id,
            idempotency_key="shared-key-xxxxxxxx",
            status=ImportCommandStatus.QUEUED,
            payload={"x": 1},
            issued_at=_utcnow(),
        )
        session.add(second)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_one_command_per_candidate(self, session: Session) -> None:
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        attempt = _make_attempt(session, sm)
        candidate = _make_candidate(session, sm, attempt)
        _make_import_command(
            session, candidate, idempotency_key="key-one-xxxxxxxx"
        )
        second = ImportCommand(
            candidate_id=candidate.id,
            idempotency_key="key-two-xxxxxxxx",
            status=ImportCommandStatus.QUEUED,
            payload={"x": 1},
            issued_at=_utcnow(),
        )
        session.add(second)
        with pytest.raises(IntegrityError):
            session.flush()


class TestImportCommandUnknownState:
    def test_unknown_status_is_persistable(self, session: Session) -> None:
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        attempt = _make_attempt(session, sm)
        candidate = _make_candidate(session, sm, attempt)
        cmd = _make_import_command(
            session,
            candidate,
            idempotency_key="key-unknown-xxxxxxxx",
            status=ImportCommandStatus.UNKNOWN,
        )
        session.expire_all()
        loaded = session.get(ImportCommand, cmd.id)
        assert loaded is not None
        assert loaded.status == ImportCommandStatus.UNKNOWN

    def test_unknown_status_value_round_trips(self, session: Session) -> None:
        # The literal string 'unknown' must be what is stored.
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        attempt = _make_attempt(session, sm)
        candidate = _make_candidate(session, sm, attempt)
        cmd = _make_import_command(
            session,
            candidate,
            idempotency_key="key-unknown-two-xxxxxxxx",
            status=ImportCommandStatus.UNKNOWN,
        )
        from sqlalchemy import text

        row = session.execute(
            text(
                "SELECT status FROM import_commands WHERE id = :id"
            ),
            {"id": cmd.id.hex},
        ).fetchone()
        assert row is not None
        assert row[0] == "unknown"

    def test_all_six_states_are_persistable(self, session: Session) -> None:
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        attempt = _make_attempt(session, sm)
        for i, status in enumerate(
            [
                ImportCommandStatus.QUEUED,
                ImportCommandStatus.IN_FLIGHT,
                ImportCommandStatus.SUCCEEDED,
                ImportCommandStatus.FAILED,
                ImportCommandStatus.UNKNOWN,
                ImportCommandStatus.RECONCILED,
            ]
        ):
            candidate = _make_candidate(
                session, sm, attempt, version=i + 1
            )
            _make_import_command(
                session,
                candidate,
                idempotency_key=f"key-status-{i}-xxxxxxxx",
                status=status,
            )
        session.flush()
        assert session.query(ImportCommand).count() == 6


class TestWalletAttemptChain:
    def test_wallet_attempts_unique_per_command_index(
        self, session: Session
    ) -> None:
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        attempt = _make_attempt(session, sm)
        candidate = _make_candidate(session, sm, attempt)
        cmd = _make_import_command(session, candidate)
        wa1 = WalletAttempt(
            import_command_id=cmd.id,
            attempt_index=1,
            status="pending",
        )
        session.add(wa1)
        session.flush()
        wa2 = WalletAttempt(
            import_command_id=cmd.id,
            attempt_index=1,  # duplicate index
            status="pending",
        )
        session.add(wa2)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_receipt_one_per_command(self, session: Session) -> None:
        inbox = _make_inbox(session)
        sm = _make_source_message(session, inbox)
        attempt = _make_attempt(session, sm)
        candidate = _make_candidate(session, sm, attempt)
        cmd = _make_import_command(session, candidate)
        wa = WalletAttempt(
            import_command_id=cmd.id,
            attempt_index=1,
            status="acknowledged",
        )
        session.add(wa)
        session.flush()
        r1 = WalletReceipt(
            import_command_id=cmd.id,
            wallet_attempt_id=wa.id,
            reconciliation_status="pending",
            received_at=_utcnow(),
        )
        session.add(r1)
        session.flush()
        r2 = WalletReceipt(
            import_command_id=cmd.id,
            wallet_attempt_id=wa.id,
            reconciliation_status="pending",
            received_at=_utcnow(),
        )
        session.add(r2)
        with pytest.raises(IntegrityError):
            session.flush()


class TestAuditEventAppendOnly:
    def test_audit_event_has_no_updated_at(self) -> None:
        from wallet_v2.persistence.base import Base

        t = Base.metadata.tables["audit_events"]
        assert "updated_at" not in t.columns

    def test_audit_event_round_trips(self, session: Session) -> None:
        event = AuditEvent(
            entity_kind="import_command",
            entity_id=uuid.uuid4(),
            event_kind="import_command_issued",
            payload={"status": "queued"},
            occurred_at=_utcnow(),
        )
        session.add(event)
        session.flush()
        loaded = session.get(AuditEvent, event.id)
        assert loaded is not None
        assert loaded.entity_kind == "import_command"
        assert loaded.payload == {"status": "queued"}

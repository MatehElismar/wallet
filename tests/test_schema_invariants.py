"""Schema-level tests for source identity, idempotency, immutability,
and the import-command state machine.

These tests run against an in-memory SQLite engine (see
``conftest.py``). They assert the *structural* invariants of the
schema: unique constraints exist where they should, immutable tables
have no ``updated_at`` column, every registered table is accounted for,
and the ``unknown`` import-command status is representable.

SQLite ``CHECK`` constraints are enforced because the conftest enables
``PRAGMA ignore_check_constraints=OFF`` and ``PRAGMA foreign_keys=ON``.
Constraint-enforcement tests against PostgreSQL are a near-term follow-up.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wallet_v2.domain.enums import (
    FinancialEventStatus,
    ImportCommandStatus,
    IntegrationMode,
    ReconciliationMethod,
    ReconciliationOutcome,
    StatementStatus,
    TransactionDirection,
)
from wallet_v2.persistence.base import Base
from wallet_v2.persistence.models import (
    AuditEvent,
    BankStatement,
    BankStatementLine,
    ExecutionRun,
    FinancialAccount,
    FinancialEvent,
    ImportCommand,
    Inbox,
    InboxCursorHistory,
    MessageContentMetadata,
    ProcessingAttempt,
    ReconciliationLink,
    ReviewDecisionRecord,
    ReviewTask,
    SourceMessage,
    StatementReviewBatch,
    TransactionCandidate,
    TransactionObservation,
    WalletAttempt,
    WalletReceipt,
)
from wallet_v2.persistence.session import session_scope


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _column_names(model_cls: type) -> set[str]:
    return {c.name for c in inspect(model_cls).columns}


def _unique_constraint_col_groups(model_cls: type) -> list[tuple[str, ...]]:
    table = inspect(model_cls).local_table
    groups: list[tuple[str, ...]] = []
    for c in table.constraints:
        if c.__class__.__name__ == "UniqueConstraint":
            groups.append(tuple(sorted(col.name for col in c.columns)))
    return groups


IMMUTABLE_MODELS: tuple[type, ...] = (
    ProcessingAttempt,
    WalletAttempt,
    ReviewDecisionRecord,
    AuditEvent,
    BankStatementLine,
    TransactionObservation,
    FinancialEvent,
    InboxCursorHistory,
)

MUTABLE_MODELS: tuple[type, ...] = (
    Inbox,
    SourceMessage,
    MessageContentMetadata,
    TransactionCandidate,
    ImportCommand,
    FinancialAccount,
    BankStatement,
    StatementReviewBatch,
    ReconciliationLink,
    ReviewTask,
    ExecutionRun,
    WalletReceipt,
)


class TestInboxIdentity:
    def test_unique_constraint_covers_provider_account_folder(self) -> None:
        groups = _unique_constraint_col_groups(Inbox)
        assert ("account_fingerprint", "folder", "provider") in groups

    def test_duplicate_inbox_triple_rejected(self, session: Session) -> None:
        inbox1 = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
        )
        session.add(inbox1)
        session.commit()

        inbox2 = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="paused",
        )
        session.add(inbox2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_same_account_different_folder_allowed(self, session: Session) -> None:
        for folder in ("INBOX", "Sent"):
            session.add(
                Inbox(
                    provider="imap",
                    account_fingerprint="a" * 64,
                    folder=folder,
                    status="active",
                )
            )
        session.commit()


class TestSourceMessageIdentity:
    def test_unique_constraint_covers_inbox_uidvalidity_uid(self) -> None:
        groups = _unique_constraint_col_groups(SourceMessage)
        assert ("inbox_id", "message_uid", "uid_validity") in groups

    def test_duplicate_source_message_rejected(self, session: Session) -> None:
        inbox = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
            uid_validity=1,
            last_seen_uid=10,
        )
        session.add(inbox)
        session.commit()

        sm1 = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=5,
            content_hash="x" * 64,
            status="received",
            received_at=_utcnow(),
        )
        session.add(sm1)
        session.commit()

        sm2 = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=5,
            content_hash="y" * 64,
            status="received",
            received_at=_utcnow(),
        )
        session.add(sm2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_same_uid_different_uidvalidity_allowed(
        self, session: Session
    ) -> None:
        inbox = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
        )
        session.add(inbox)
        session.commit()

        for uv in (1, 2):
            session.add(
                SourceMessage(
                    inbox_id=inbox.id,
                    uid_validity=uv,
                    message_uid=5,
                    content_hash="x" * 64,
                    status="received",
                    received_at=_utcnow(),
                )
            )
        session.commit()


class TestAttemptIdempotency:
    def test_unique_constraint_on_idempotency_key(self) -> None:
        groups = _unique_constraint_col_groups(ProcessingAttempt)
        assert ("idempotency_key",) in groups

    def test_unique_constraint_on_source_message_index(self) -> None:
        groups = _unique_constraint_col_groups(ProcessingAttempt)
        assert ("attempt_index", "source_message_id") in groups

    def test_duplicate_idempotency_key_rejected(self, session: Session) -> None:
        inbox = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
        )
        session.add(inbox)
        session.commit()
        sm = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=1,
            content_hash="x" * 64,
            status="received",
            received_at=_utcnow(),
        )
        session.add(sm)
        session.commit()

        a1 = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=1,
            idempotency_key="key-aaaaaaaaaaaaaaaa",
            status="pending",
        )
        session.add(a1)
        session.commit()

        a2 = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=2,
            idempotency_key="key-aaaaaaaaaaaaaaaa",
            status="pending",
        )
        session.add(a2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestImportCommandIdempotencyAndUnknown:
    def test_unique_constraint_on_idempotency_key(self) -> None:
        groups = _unique_constraint_col_groups(ImportCommand)
        assert ("idempotency_key",) in groups

    def test_unique_constraint_on_candidate_id(self) -> None:
        groups = _unique_constraint_col_groups(ImportCommand)
        assert ("candidate_id",) in groups

    def test_unique_constraint_on_financial_event_id(self) -> None:
        groups = _unique_constraint_col_groups(ImportCommand)
        assert ("financial_event_id",) in groups

    def test_unknown_status_is_representable(self) -> None:
        assert ImportCommandStatus.UNKNOWN.value == "unknown"
        assert ImportCommandStatus.UNKNOWN in ImportCommandStatus

    def test_state_machine_includes_all_required_states(self) -> None:
        values = {s.value for s in ImportCommandStatus}
        assert {
            "queued",
            "in_flight",
            "succeeded",
            "failed",
            "unknown",
            "reconciled",
        }.issubset(values)

    def test_insert_with_unknown_status_succeeds(self, session: Session) -> None:
        inbox = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
        )
        session.add(inbox)
        session.commit()
        sm = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=1,
            content_hash="x" * 64,
            status="received",
            received_at=_utcnow(),
        )
        session.add(sm)
        session.commit()
        attempt = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=1,
            idempotency_key="attempt-key-aaaaaaaaaaaaaaaa",
            status="succeeded",
        )
        session.add(attempt)
        session.commit()
        candidate = TransactionCandidate(
            source_message_id=sm.id,
            attempt_id=attempt.id,
            candidate_version=1,
            status="approved",
            direction="debit",
            amount_minor=100,
            currency="USD",
            merchant="Merchant",
        )
        session.add(candidate)
        session.commit()

        cmd = ImportCommand(
            candidate_id=candidate.id,
            idempotency_key="import-key-aaaaaaaaaaaaaaaa",
            status=ImportCommandStatus.UNKNOWN,
            payload={"direction": "debit", "amount_minor": 100},
            issued_at=_utcnow(),
        )
        session.add(cmd)
        session.commit()
        session.refresh(cmd)
        assert cmd.status == ImportCommandStatus.UNKNOWN

    def test_duplicate_idempotency_key_rejected(self, session: Session) -> None:
        inbox = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
        )
        session.add(inbox)
        session.commit()
        sm = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=1,
            content_hash="x" * 64,
            status="received",
            received_at=_utcnow(),
        )
        session.add(sm)
        session.commit()
        attempt = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=1,
            idempotency_key="attempt-key-aaaaaaaaaaaaaaaa",
            status="succeeded",
        )
        session.add(attempt)
        session.commit()
        candidate = TransactionCandidate(
            source_message_id=sm.id,
            attempt_id=attempt.id,
            candidate_version=1,
            status="approved",
            direction="debit",
            amount_minor=100,
            currency="USD",
            merchant="Merchant",
        )
        session.add(candidate)
        session.commit()

        cmd1 = ImportCommand(
            candidate_id=candidate.id,
            idempotency_key="import-key-aaaaaaaaaaaaaaaa",
            status=ImportCommandStatus.QUEUED,
            payload={"direction": "debit"},
            issued_at=_utcnow(),
        )
        session.add(cmd1)
        session.commit()

        cmd2 = ImportCommand(
            candidate_id=candidate.id,
            idempotency_key="import-key-aaaaaaaaaaaaaaaa",
            status=ImportCommandStatus.QUEUED,
            payload={"direction": "debit"},
            issued_at=_utcnow(),
        )
        session.add(cmd2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestImmutabilityInvariants:
    @pytest.mark.parametrize("model_cls", IMMUTABLE_MODELS)
    def test_immutable_tables_have_no_updated_at(self, model_cls: type) -> None:
        cols = _column_names(model_cls)
        assert "created_at" in cols, f"{model_cls.__name__} missing created_at"
        assert "updated_at" not in cols, f"{model_cls.__name__} should not have updated_at"

    @pytest.mark.parametrize("model_cls", MUTABLE_MODELS)
    def test_mutable_tables_have_both_timestamps(self, model_cls: type) -> None:
        cols = _column_names(model_cls)
        assert "created_at" in cols, f"{model_cls.__name__} missing created_at"
        assert "updated_at" in cols, f"{model_cls.__name__} missing updated_at"


class TestMetadataCompleteness:
    def test_all_tables_registered(self) -> None:
        table_names = set(Base.metadata.tables.keys())
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
        missing = expected - table_names
        extra = table_names - expected
        assert not missing, f"Tables missing from metadata: {missing}"
        assert not extra, f"Unexpected tables in metadata: {extra}"


class TestDoubleBatchApprovalNoDuplicateEvents:
    def test_double_approval_rejected(
        self, session: Session
    ) -> None:
        run = ExecutionRun(
            mode=IntegrationMode.DRY_RUN,
            trigger="test",
            label="double-approval-test",
            started_at=_utcnow(),
        )
        session.add(run)
        session.commit()

        account = FinancialAccount(
            issuer="Test Bank",
            external_reference="acct-123",
        )
        session.add(account)
        session.commit()

        inbox = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
        )
        session.add(inbox)
        session.commit()

        sm = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=50,
            content_hash="x" * 64,
            status="received",
            received_at=_utcnow(),
        )
        session.add(sm)
        session.commit()

        attempt = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=1,
            idempotency_key="attempt-dba-a",
            status="succeeded",
        )
        session.add(attempt)
        session.commit()

        statement = BankStatement(
            source_message_id=sm.id,
            processing_attempt_id=attempt.id,
            account_id=account.id,
            statement_version=1,
            status=StatementStatus.OPEN,
            document_fingerprint="f" * 64,
            statement_date=date(2025, 1, 31),
            currency="USD",
        )
        session.add(statement)
        session.commit()

        batch = StatementReviewBatch(statement_id=statement.id, state="open")
        session.add(batch)
        session.commit()

        line = BankStatementLine(
            statement_id=statement.id,
            line_index=1,
            line_fingerprint="lf" * 32,
            direction=TransactionDirection.DEBIT,
            amount_minor=5000,
            currency="USD",
            merchant="Office Supplies",
            event_status=FinancialEventStatus.POSTED,
        )
        session.add(line)
        session.commit()

        link = ReconciliationLink(
            statement_line_id=line.id,
            outcome=ReconciliationOutcome.NEW,
            method=ReconciliationMethod.NONE,
            confidence=1.0,
        )
        session.add(link)
        session.commit()

        from wallet_v2.application.service import WalletWorkflow, WorkflowError
        from wallet_v2.persistence.session import session_scope

        wf = WalletWorkflow(session)
        events = wf.approve_statement_batch(
            run=run, batch=batch, reviewer_id="tester"
        )
        assert len(events) == 1

        with pytest.raises(WorkflowError, match="only an open statement review batch"):
            wf.approve_statement_batch(
                run=run, batch=batch, reviewer_id="tester"
            )

        financial_events = session.query(FinancialEvent).filter(
            FinancialEvent.statement_line_id == line.id
        ).all()
        assert len(financial_events) == 1


class TestImportCommandQueuedExplicit:
    def test_constructor_sets_queued_by_default(self, session: Session) -> None:
        inbox = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
        )
        session.add(inbox)
        session.commit()
        sm = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=99,
            content_hash="x" * 64,
            status="received",
            received_at=_utcnow(),
        )
        session.add(sm)
        session.commit()
        attempt = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=1,
            idempotency_key="queued-default-test",
            status="succeeded",
        )
        session.add(attempt)
        session.commit()
        candidate = TransactionCandidate(
            source_message_id=sm.id,
            attempt_id=attempt.id,
            candidate_version=1,
            status="approved",
            direction="debit",
            amount_minor=100,
            currency="USD",
            merchant="Merchant",
        )
        session.add(candidate)
        session.commit()

        cmd = ImportCommand(
            candidate_id=candidate.id,
            idempotency_key="queued-test-key-bbbb",
            payload={"key": "value"},
            issued_at=_utcnow(),
        )
        session.add(cmd)
        session.commit()
        session.refresh(cmd)
        assert cmd.status == ImportCommandStatus.QUEUED


class TestIgnoreCheckConstraintsEnabled:
    def test_check_constraint_enforcement(self, session: Session) -> None:
        """Verify SQLite CHECK constraints are enforced because
        ignore_check_constraints=OFF in the test engine."""
        inbox = Inbox(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status="active",
        )
        session.add(inbox)
        session.commit()
        sm = SourceMessage(
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=1,
            content_hash="x" * 64,
            status="received",
            received_at=_utcnow(),
        )
        session.add(sm)
        session.commit()
        attempt = ProcessingAttempt(
            source_message_id=sm.id,
            attempt_index=1,
            idempotency_key="chk-test-aaaa",
            status="succeeded",
        )
        session.add(attempt)
        session.commit()

        candidate = TransactionCandidate(
            source_message_id=sm.id,
            attempt_id=attempt.id,
            candidate_version=1,
            status="approved",
            direction="debit",
            amount_minor=0,
            currency="USD",
            merchant="Merchant",
        )
        session.add(candidate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestSessionScopeReuse:
    def test_session_scope_imported_from_persistence_dot_session(self, sqlite_engine):
        from sqlalchemy.orm import sessionmaker

        factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
        with session_scope(factory) as s:
            result = s.execute(text("SELECT 1")).scalar()
            assert result == 1

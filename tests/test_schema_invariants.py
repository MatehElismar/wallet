"""Schema-level tests for source identity, idempotency, and the
import-command state machine.

These tests run against an in-memory SQLite engine (see
``conftest.py``). They assert the *structural* invariants of the
schema: unique constraints exist where they should, immutable tables
have no ``updated_at`` column, and the ``unknown`` import-command
status is representable.

SQLite does not enforce ``CHECK`` constraints by default; we enable
foreign keys but do not rely on CHECK enforcement here. Constraint-
enforcement tests against PostgreSQL are a near-term follow-up.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wallet_v2.domain.enums import ImportCommandStatus
from wallet_v2.persistence.base import Base
from wallet_v2.persistence.models import (
    ImportCommand,
    Inbox,
    InboxCursorHistory,
    ProcessingAttempt,
    SourceMessage,
    TransactionCandidate,
)


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

        # Same candidate cannot produce a second import command (unique on
        # candidate_id), and the same idempotency_key cannot be reused.
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
    @pytest.mark.parametrize(
        "model_cls",
        [
            ProcessingAttempt,
        ],
    )
    def test_immutable_tables_have_no_updated_at(
        self, model_cls: type
    ) -> None:
        cols = _column_names(model_cls)
        assert "created_at" in cols
        assert "updated_at" not in cols

    @pytest.mark.parametrize(
        "model_cls",
        [Inbox, SourceMessage, TransactionCandidate, ImportCommand],
    )
    def test_mutable_tables_have_both_timestamps(
        self, model_cls: type
    ) -> None:
        cols = _column_names(model_cls)
        assert "created_at" in cols
        assert "updated_at" in cols


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
        }
        assert expected.issubset(table_names)

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
from pathlib import Path

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
    AccountMapping,
    AdvisoryResearch,
    AuditEvent,
    BankStatement,
    BankStatementLine,
    CatalogSyncCursor,
    CatalogSyncSnapshot,
    EnrichmentDecision,
    ExecutionRun,
    FinancialAccount,
    FinancialEvent,
    ImportCommand,
    Inbox,
    InboxCursorHistory,
    McpProfileSnapshot,
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
    CatalogSyncSnapshot,
    McpProfileSnapshot,
    EnrichmentDecision,
)

MUTABLE_MODELS: tuple[type, ...] = (
    AccountMapping,
    AdvisoryResearch,
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
    CatalogSyncCursor,
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


class TestMcpModelDefaultsConsistentWithMigration:
    """Verify that every nullable JSONB column in the MCP ORM models has no
    Python-side ``default=dict``, matching the migration (which declares no
    ``server_default`` for nullable JSONB columns)."""

    def test_no_python_default_on_nullable_jsonb_columns(self) -> None:
        from wallet_v2.persistence.models.mcp import (
            AdvisoryResearch,
            EnrichmentDecision,
            McpProfileSnapshot,
        )

        models = [McpProfileSnapshot, AdvisoryResearch, EnrichmentDecision]
        for model in models:
            for col in model.__table__.columns:
                if col.type.__class__.__name__ == "JSONB" and col.nullable:
                    # The mapped_column default should be None (no Python-side default)
                    # when the column is nullable and has no server_default.
                    assert col.default is None or col.server_default is not None, (
                        f"{model.__tablename__}.{col.name} has Python-side "
                        f"default {col.default!r} but is nullable with no server_default"
                    )


class TestEnrichmentDecisionSelectedLabelIdsType:
    """Verify ``EnrichmentDecision.selected_label_ids`` is typed as a JSON
    array of strings (``Mapped[list[str] | None]``), not a free-form dict.

    The migration declares the column as ``JSONB``; the ORM typing tightens
    that to ``list[str] | None`` so callers cannot accidentally persist a
    dict-shaped payload.
    """

    def test_selected_label_ids_is_list_of_strings_or_none(self) -> None:
        from typing import get_args, get_origin, get_type_hints

        from sqlalchemy.orm import Mapped

        from wallet_v2.persistence.models.mcp import EnrichmentDecision

        hints = get_type_hints(EnrichmentDecision)
        ann = hints["selected_label_ids"]
        assert get_origin(ann) is Mapped
        (inner,) = get_args(ann)
        # inner is list[str] | None — a PEP 604 union
        inner_args = get_args(inner)
        assert set(inner_args) == {list[str], type(None)}
        list_arg = next(a for a in inner_args if get_origin(a) is list)
        assert get_args(list_arg) == (str,)


class TestMcpProfileSnapshotGrantedScopesColumn:
    """Verify the persisted ``McpProfileSnapshot`` column is named
    ``granted_scopes`` (renamed from ``required_scopes`` pre-deployment)
    in both the ORM and the migration."""

    def test_orm_has_granted_scopes_column(self) -> None:
        from wallet_v2.persistence.models.mcp import McpProfileSnapshot

        col_names = {c.name for c in McpProfileSnapshot.__table__.columns}
        assert "granted_scopes" in col_names
        assert "required_scopes" not in col_names

    def test_migration_0009_declares_granted_scopes(self) -> None:
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "0009_mcp_advisory_enrichment.py"
        )
        source = migration_path.read_text()
        assert 'sa.Column("granted_scopes"' in source
        assert 'sa.Column("required_scopes"' not in source

    def test_migration_0009_downgrade_drops_no_partial_index(self) -> None:
        """The ``enrichment_decisions`` partial unique index lives on the
        table; dropping the table cascades the index, so a separate
        ``DROP INDEX`` line in downgrade is redundant and must not be present.
        """
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "0009_mcp_advisory_enrichment.py"
        )
        source = migration_path.read_text()
        # Slice the downgrade() function source out for an isolated check.
        downgrade_start = source.index("def downgrade()")
        downgrade_body = source[downgrade_start:]
        assert "DROP INDEX" not in downgrade_body
        assert "drop_index" not in downgrade_body


class TestMcpProfileSnapshotGrantedScopesTyping:
    """Verify ``McpProfileSnapshot.granted_scopes`` is typed as a JSON array
    of strings (``Mapped[list[str]]``), matching the observed
    ``get_client_profile.grantedScopes`` payload shape — not a free-form
    dict.
    """

    def test_orm_type_hint_is_list_of_strings(self) -> None:
        from typing import get_args, get_origin, get_type_hints

        from sqlalchemy.orm import Mapped

        from wallet_v2.persistence.models.mcp import McpProfileSnapshot

        hints = get_type_hints(McpProfileSnapshot)
        ann = hints["granted_scopes"]
        assert get_origin(ann) is Mapped
        (inner,) = get_args(ann)
        # inner must be list[str] directly — NOT dict and NOT Optional.
        assert get_origin(inner) is list, (
            "granted_scopes must be typed as list[str], not "
            f"{inner!r}"
        )
        assert get_args(inner) == (str,)
        # Sanity: the inner type is not a dict origin.
        assert get_origin(inner) is not dict

    def test_granted_scopes_round_trips_as_list_of_strings(
        self, session: Session
    ) -> None:
        from wallet_v2.persistence.models.mcp import McpProfileSnapshot

        snapshot = McpProfileSnapshot(
            sync_state="complete",
            granted_scopes=["records.read", "accounts.read", "categories.write"],
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        assert isinstance(snapshot.granted_scopes, list)
        assert snapshot.granted_scopes == [
            "records.read",
            "accounts.read",
            "categories.write",
        ]
        assert all(isinstance(s, str) for s in snapshot.granted_scopes)

    def test_granted_scopes_defaults_to_empty_list(self, session: Session) -> None:
        from wallet_v2.persistence.models.mcp import McpProfileSnapshot

        snapshot = McpProfileSnapshot(sync_state="pending")
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        assert snapshot.granted_scopes == []
        assert isinstance(snapshot.granted_scopes, list)

    def test_migration_0009_granted_scopes_server_default_is_empty_array(self) -> None:
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "0009_mcp_advisory_enrichment.py"
        )
        source = migration_path.read_text()
        # An empty JSON array server default matches the list[str] ORM typing;
        # an empty object "{}" would be inconsistent with list typing.
        assert 'server_default="[]"' in source
        assert 'server_default="{}"' not in source


class TestAdvisoryResearchTargetFkDeletionPolicy:
    """Verify the AdvisoryResearch target FKs use RESTRICT (not SET NULL).

    The ``advisory_research`` table has an exactly-one-target XOR CHECK
    constraint over ``(candidate_id, financial_event_id)``. If either target
    FK used ``ON DELETE SET NULL``, deleting a target row would null out one
    side and produce an invalid both-null row, violating the CHECK. Auditable
    research requires the database to refuse deletion of a referenced target,
    so both target FKs must use ``RESTRICT``. The ``profile_snapshot_id`` FK
    is intentionally left as ``SET NULL`` because it is not part of the XOR.
    """

    @staticmethod
    def _single_fk(table, col_name: str):
        col = table.columns[col_name]
        fks = list(col.foreign_keys)
        assert len(fks) == 1, f"{col_name} should have exactly one FK"
        return fks[0]

    def test_candidate_fk_is_restrict_not_set_null(self) -> None:
        from wallet_v2.persistence.models.mcp import AdvisoryResearch

        fk = self._single_fk(AdvisoryResearch.__table__, "candidate_id")
        assert (fk.ondelete or "").upper() == "RESTRICT", (
            f"candidate_id FK must be RESTRICT, got {fk.ondelete!r}"
        )

    def test_financial_event_fk_is_restrict_not_set_null(self) -> None:
        from wallet_v2.persistence.models.mcp import AdvisoryResearch

        fk = self._single_fk(AdvisoryResearch.__table__, "financial_event_id")
        assert (fk.ondelete or "").upper() == "RESTRICT", (
            f"financial_event_id FK must be RESTRICT, got {fk.ondelete!r}"
        )

    def test_profile_snapshot_fk_remains_set_null(self) -> None:
        from wallet_v2.persistence.models.mcp import AdvisoryResearch

        fk = self._single_fk(AdvisoryResearch.__table__, "profile_snapshot_id")
        assert (fk.ondelete or "").upper() == "SET NULL", (
            "profile_snapshot_id FK should remain SET NULL — it is not part "
            f"of the XOR target policy; got {fk.ondelete!r}"
        )

    def test_no_target_fk_uses_set_null(self) -> None:
        from wallet_v2.persistence.models.mcp import AdvisoryResearch

        for col_name in ("candidate_id", "financial_event_id"):
            fk = self._single_fk(AdvisoryResearch.__table__, col_name)
            assert (fk.ondelete or "").upper() != "SET NULL", (
                f"{col_name} FK must not be SET NULL — XOR CHECK + SET NULL "
                "permits an invalid both-null row on target deletion"
            )

    def test_migration_0009_uses_restrict_for_target_fks(self) -> None:
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "0009_mcp_advisory_enrichment.py"
        )
        source = migration_path.read_text()
        # Both target FKs must declare RESTRICT...
        assert source.count('ondelete="RESTRICT"') >= 2, (
            "Both advisory_research target FKs (candidate, financial_event) "
            "must declare ondelete=\"RESTRICT\" in migration 0009"
        )
        # ...and only the profile_snapshot FK may remain SET NULL (exactly one).
        assert source.count('ondelete="SET NULL"') == 1, (
            "Only the profile_snapshot FK should use SET NULL in migration "
            "0009; both target FKs must use RESTRICT."
        )

    def test_deleting_candidate_with_research_is_blocked(
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
            idempotency_key="restrict-candidate-attempt",
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
        )
        session.add(candidate)
        session.commit()

        research = AdvisoryResearch(
            candidate_id=candidate.id,
            evidence_grade="no_recommendation",
        )
        session.add(research)
        session.commit()

        session.delete(candidate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_deleting_financial_event_with_research_is_blocked(
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
            idempotency_key="restrict-event-attempt",
            status="succeeded",
        )
        session.add(attempt)
        session.commit()
        account = FinancialAccount(
            issuer="Test", external_reference="acct-restrict-event"
        )
        session.add(account)
        session.commit()
        stmt = BankStatement(
            source_message_id=sm.id,
            processing_attempt_id=attempt.id,
            account_id=account.id,
            statement_version=1,
            status=StatementStatus.OPEN,
            document_fingerprint="f" * 64,
            statement_date=date(2025, 1, 1),
            currency="USD",
        )
        session.add(stmt)
        session.commit()
        line = BankStatementLine(
            statement_id=stmt.id,
            line_index=1,
            line_fingerprint="lf" * 32,
            direction=TransactionDirection.DEBIT,
            amount_minor=100,
            currency="USD",
        )
        session.add(line)
        session.commit()
        event = FinancialEvent(
            account_id=account.id,
            statement_line_id=line.id,
            direction=TransactionDirection.DEBIT,
            amount_minor=100,
            currency="USD",
            merchant="Test",
        )
        session.add(event)
        session.commit()

        research = AdvisoryResearch(
            financial_event_id=event.id,
            evidence_grade="no_recommendation",
        )
        session.add(research)
        session.commit()

        session.delete(event)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestAdvisoryResearchXorTarget:
    """Verify the one-target CHECK constraint on advisory_research.

    Exactly one of (candidate_id, financial_event_id) must be non-null.
    """

    def test_both_null_rejected(self, session: Session) -> None:
        research = AdvisoryResearch(evidence_grade="no_recommendation")
        session.add(research)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_both_set_rejected(self, session: Session) -> None:
        from wallet_v2.persistence.models import FinancialEvent, TransactionCandidate

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
            idempotency_key="xor-test-attempt",
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
        )
        session.add(candidate)
        session.commit()

        account = FinancialAccount(issuer="Test", external_reference="acct-xor")
        session.add(account)
        session.commit()
        stmt = BankStatement(
            source_message_id=sm.id,
            processing_attempt_id=attempt.id,
            account_id=account.id,
            statement_version=1,
            status=StatementStatus.OPEN,
            document_fingerprint="f" * 64,
            statement_date=date(2025, 1, 1),
            currency="USD",
        )
        session.add(stmt)
        session.commit()
        line = BankStatementLine(
            statement_id=stmt.id,
            line_index=1,
            line_fingerprint="lf" * 32,
            direction=TransactionDirection.DEBIT,
            amount_minor=100,
            currency="USD",
        )
        session.add(line)
        session.commit()
        event = FinancialEvent(
            account_id=account.id,
            statement_line_id=line.id,
            direction=TransactionDirection.DEBIT,
            amount_minor=100,
            currency="USD",
            merchant="Test",
        )
        session.add(event)
        session.commit()

        research = AdvisoryResearch(
            candidate_id=candidate.id,
            financial_event_id=event.id,
            evidence_grade="no_recommendation",
        )
        session.add(research)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_candidate_only_succeeds(self, session: Session) -> None:
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
            idempotency_key="xor-candidate-only",
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
        )
        session.add(candidate)
        session.commit()

        research = AdvisoryResearch(
            candidate_id=candidate.id,
            evidence_grade="no_recommendation",
        )
        session.add(research)
        session.commit()
        session.refresh(research)
        assert research.candidate_id == candidate.id
        assert research.financial_event_id is None

    def test_financial_event_only_succeeds(self, session: Session) -> None:
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
            idempotency_key="xor-event-only",
            status="succeeded",
        )
        session.add(attempt)
        session.commit()

        account = FinancialAccount(issuer="Test", external_reference="acct-xor2")
        session.add(account)
        session.commit()
        stmt = BankStatement(
            source_message_id=sm.id,
            processing_attempt_id=attempt.id,
            account_id=account.id,
            statement_version=1,
            status=StatementStatus.OPEN,
            document_fingerprint="f" * 64,
            statement_date=date(2025, 1, 1),
            currency="USD",
        )
        session.add(stmt)
        session.commit()
        line = BankStatementLine(
            statement_id=stmt.id,
            line_index=1,
            line_fingerprint="lf" * 32,
            direction=TransactionDirection.DEBIT,
            amount_minor=100,
            currency="USD",
        )
        session.add(line)
        session.commit()
        event = FinancialEvent(
            account_id=account.id,
            statement_line_id=line.id,
            direction=TransactionDirection.DEBIT,
            amount_minor=100,
            currency="USD",
            merchant="Test",
        )
        session.add(event)
        session.commit()

        research = AdvisoryResearch(
            financial_event_id=event.id,
            evidence_grade="no_recommendation",
        )
        session.add(research)
        session.commit()
        session.refresh(research)
        assert research.financial_event_id == event.id
        assert research.candidate_id is None


class TestEnrichmentDecisionFinalizedUnique:
    """Verify the partial unique index declaration on enrichment_decisions.

    The ``uq_enrichment_decisions_one_finalized`` partial unique index
    ensures at most one ``finalized=true`` row per ``financial_event_id``.
    This index uses ``postgresql_where`` and is only enforceable on
    PostgreSQL; the SQLite test harness verifies the constraint is
    correctly declared in the model metadata.
    """

    def test_partial_unique_index_declared_in_metadata(self) -> None:
        table = Base.metadata.tables["enrichment_decisions"]
        constraint_names = {idx.name for idx in table.indexes}
        assert "uq_enrichment_decisions_one_finalized" in constraint_names

        idx = next(
            idx
            for idx in table.indexes
            if idx.name == "uq_enrichment_decisions_one_finalized"
        )
        assert idx.unique is True
        expr_names = [expr.name for expr in idx.expressions]
        assert expr_names == ["financial_event_id"]
        assert idx.dialect_kwargs.get("postgresql_where") == "finalized IS TRUE"


class TestMetadataCompleteness:
    def test_all_tables_registered(self) -> None:
        table_names = set(Base.metadata.tables.keys())
        expected = {
            "account_mappings",
            "advisory_research",
            "enrichment_decisions",
            "inboxes",
            "inbox_cursor_history",
            "mcp_profile_snapshots",
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
            "push_subscriptions",
            "notification_outbox",
            "catalog_sync_cursors",
            "catalog_sync_snapshots",
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

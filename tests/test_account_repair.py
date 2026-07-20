"""Hermetic tests for AccountRepairService.

Covers:
- ``canonicalise_and_merge`` — idempotent merge of duplicate accounts
- ``repair_qik_account`` — full repair with validated mapping
- Conflict detection (wallet_account_reference divergence)
- Dependent record reassignment (statements, events, observations)
- Idempotency
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from wallet_v2.application.account_repair import (
    AccountRepairError,
    AccountRepairResult,
    AccountRepairService,
)
from wallet_v2.application.account_mapping import AccountMappingService
from wallet_v2.domain.enums import (
    AuditEventKind,
    DocumentKind,
    IntegrationMode,
    FinancialEventStatus,
    ObservationStatus,
    ReconciliationOutcome,
    StatementStatus,
    TransactionDirection,
)
from wallet_v2.domain.reference import canonical_external_reference
from wallet_v2.persistence.models import (
    AccountMapping,
    AuditEvent,
    BankStatement,
    BankStatementLine,
    CatalogSyncCursor,
    CatalogSyncSnapshot,
    ExecutionRun,
    FinancialAccount,
    FinancialEvent,
    ReconciliationLink,
    StatementReviewBatch,
    TransactionObservation,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_account(
    session: Session,
    issuer: str = "Qik",
    external_reference: str = "2197",
) -> FinancialAccount:
    acct = FinancialAccount(issuer=issuer, external_reference=external_reference)
    session.add(acct)
    session.flush()
    return acct


def _make_accounts_snapshot(
    session: Session,
    *,
    items: list[dict[str, Any]] | None = None,
    version: int = 1,
    with_cursor: bool = True,
) -> CatalogSyncSnapshot:
    if items is None:
        items = [
            {"id": "37c86c4f-5370-466b-a36b-40b533f6cf31", "name": "QIK CC 2197", "archived": False},
        ]
    snap = CatalogSyncSnapshot(
        resource_kind="accounts",
        snapshot_version=version,
        catalog_data={
            "version": 1,
            "resource_kind": "accounts",
            "snapshot_version": version,
            "item_count": len(items),
            "items": items,
        },
    )
    session.add(snap)
    session.flush()
    if with_cursor:
        cursor = session.scalar(
            select(CatalogSyncCursor).where(CatalogSyncCursor.resource_kind == "accounts")
        )
        if cursor is None:
            cursor = CatalogSyncCursor(resource_kind="accounts")
            session.add(cursor)
        cursor.current_snapshot_id = snap.id
        cursor.last_synced_at = _utcnow()
        session.flush()
    return snap


def _make_source_message(session: Session) -> object:
    from wallet_v2.persistence.models import Inbox, SourceMessage
    from wallet_v2.domain.enums import MailboxSourceStatus, SourceMessageStatus

    inbox = Inbox(
        provider="test",
        account_fingerprint="a" * 64,
        folder="INBOX",
        status=MailboxSourceStatus.ACTIVE,
    )
    session.add(inbox)
    session.flush()
    sm = SourceMessage(
        inbox_id=inbox.id,
        uid_validity=1,
        message_uid=1,
        content_hash="0" * 64,
        status=SourceMessageStatus.RECEIVED,
        received_at=_utcnow(),
    )
    session.add(sm)
    session.flush()
    return sm


def _make_attempt(session: Session, source_message: object) -> object:
    from wallet_v2.persistence.models import ProcessingAttempt
    from wallet_v2.domain.enums import AttemptStatus

    attempt = ProcessingAttempt(
        source_message_id=source_message.id,
        attempt_index=1,
        idempotency_key="test-attempt",
        status=AttemptStatus.SUCCEEDED,
    )
    session.add(attempt)
    session.flush()
    return attempt


def _make_statement(
    session: Session,
    account: FinancialAccount,
    status: StatementStatus = StatementStatus.APPROVED,
) -> BankStatement:
    source = _make_source_message(session)
    attempt = _make_attempt(session, source)
    stmt = BankStatement(
        source_message_id=source.id,
        processing_attempt_id=attempt.id,
        account_id=account.id,
        statement_version=1,
        status=status,
        document_fingerprint="f" + "0" * 63,
        currency="USD",
    )
    session.add(stmt)
    session.flush()
    return stmt


def _make_event(
    session: Session,
    account: FinancialAccount,
    statement: BankStatement,
) -> FinancialEvent:
    line = BankStatementLine(
        statement_id=statement.id,
        line_index=1,
        line_fingerprint="lf" + "0" * 62,
        direction=TransactionDirection.DEBIT,
        amount_minor=1000,
        currency="USD",
        event_status=FinancialEventStatus.POSTED,
    )
    session.add(line)
    session.flush()
    link = ReconciliationLink(
        statement_line_id=line.id,
        outcome=ReconciliationOutcome.NEW,
        method="none",
        confidence=1.0,
    )
    session.add(link)
    session.flush()
    event = FinancialEvent(
        account_id=account.id,
        statement_line_id=line.id,
        status=FinancialEventStatus.POSTED,
        direction=TransactionDirection.DEBIT,
        amount_minor=1000,
        currency="USD",
    )
    session.add(event)
    session.flush()
    return event


def _make_candidate(session: Session, source: object, attempt: object) -> object:
    from wallet_v2.persistence.models import TransactionCandidate
    from wallet_v2.domain.enums import CandidateStatus

    cand = TransactionCandidate(
        source_message_id=source.id,
        attempt_id=attempt.id,
        source_item_index=1,
        candidate_version=1,
        status=CandidateStatus.UNDER_REVIEW,
        direction=TransactionDirection.DEBIT,
        amount_minor=1000,
        currency="USD",
    )
    session.add(cand)
    session.flush()
    return cand


def _make_observation(
    session: Session,
    account: FinancialAccount,
) -> TransactionObservation:
    source = _make_source_message(session)
    attempt = _make_attempt(session, source)
    cand = _make_candidate(session, source, attempt)
    obs = TransactionObservation(
        source_message_id=source.id,
        processing_attempt_id=attempt.id,
        account_id=account.id,
        candidate_id=cand.id,
        source_item_index=1,
        observation_version=1,
        status=ObservationStatus.PROVISIONAL,
        direction=TransactionDirection.DEBIT,
        amount_minor=1000,
        currency="USD",
    )
    session.add(obs)
    session.flush()
    return obs


# ── canonicalise_and_merge tests ──────────────────────────────────────


class TestCanonicaliseAndMerge:
    def test_merges_two_duplicates_into_canonical(self, session: Session) -> None:
        dup1 = _make_account(session, external_reference="*2197")
        dup2 = _make_account(session, external_reference="************2197")

        svc = AccountRepairService(session)
        result = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197", "************2197"]
        )
        session.commit()

        assert result.survivor_account_id is not None
        assert set(result.merged_account_ids) == {str(dup1.id), str(dup2.id)}

        accounts = session.scalars(select(FinancialAccount)).all()
        assert len(accounts) == 1
        assert accounts[0].external_reference == "2197"

    def test_idempotent_when_already_merged(self, session: Session) -> None:
        _make_account(session, external_reference="2197")

        svc = AccountRepairService(session)
        result1 = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197", "************2197"]
        )
        session.commit()
        result2 = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197", "************2197"]
        )
        session.commit()

        assert result1.merged_account_ids == []
        assert result2.merged_account_ids == []
        accounts = session.scalars(select(FinancialAccount)).all()
        assert len(accounts) == 1

    def test_idempotent_no_duplicates(self, session: Session) -> None:
        acct = _make_account(session, external_reference="*2197")

        svc = AccountRepairService(session)
        result = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197"]
        )
        session.commit()

        # The original *2197 was merged into the newly-created canonical 2197
        accounts = session.scalars(select(FinancialAccount)).all()
        assert len(accounts) == 1
        assert accounts[0].external_reference == "2197"
        deleted = session.get(FinancialAccount, acct.id)
        assert deleted is None

    def test_reassigns_statements(self, session: Session) -> None:
        dup = _make_account(session, external_reference="*2197")
        stmt = _make_statement(session, dup)

        svc = AccountRepairService(session)
        result = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197"]
        )
        session.commit()

        assert result.reassigned.get("bank_statements", 0) >= 1
        # statement should now point to survivor
        survivor = session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.external_reference == "2197"
            )
        )
        assert survivor is not None
        session.expire_all()
        reloaded = session.get(BankStatement, stmt.id)
        assert reloaded is not None
        assert reloaded.account_id == survivor.id

    def test_reassigns_financial_events(self, session: Session) -> None:
        dup = _make_account(session, external_reference="*2197")
        stmt = _make_statement(session, dup)
        event = _make_event(session, dup, stmt)

        svc = AccountRepairService(session)
        result = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197"]
        )
        session.commit()

        assert result.reassigned.get("financial_events", 0) >= 1
        survivor = session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.external_reference == "2197"
            )
        )
        session.expire_all()
        reloaded = session.get(FinancialEvent, event.id)
        assert reloaded is not None
        assert reloaded.account_id == survivor.id

    def test_reassigns_observations(self, session: Session) -> None:
        dup = _make_account(session, external_reference="*2197")
        obs = _make_observation(session, dup)

        svc = AccountRepairService(session)
        result = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197"]
        )
        session.commit()

        assert result.reassigned.get("transaction_observations", 0) >= 1
        survivor = session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.external_reference == "2197"
            )
        )
        session.expire_all()
        reloaded = session.get(TransactionObservation, obs.id)
        assert reloaded is not None
        assert reloaded.account_id == survivor.id

    def test_refuses_wallet_reference_mismatch(self, session: Session) -> None:
        _make_account(session, external_reference="2197", issuer="Qik")
        dup = _make_account(session, external_reference="*2197", issuer="Qik")
        dup.wallet_account_reference = "old-ref"
        session.flush()

        svc = AccountRepairService(session)
        with pytest.raises(AccountRepairError, match="conflicting legacy Wallet"):
            svc.canonicalise_and_merge(
                issuer="Qik", raw_references=["*2197", "2197"]
            )

    def test_refuses_references_with_different_canonical_values(self, session: Session) -> None:
        svc = AccountRepairService(session)

        with pytest.raises(AccountRepairError, match="one non-blank canonical"):
            svc.canonicalise_and_merge(
                issuer="Qik", raw_references=["*2197", "************2198"]
            )

    def test_refuses_duplicate_with_mapping_history(self, session: Session) -> None:
        dup = _make_account(session, external_reference="*2197")
        snapshot = _make_accounts_snapshot(session)
        AccountMappingService(session).create_mapping(
            financial_account_id=dup.id,
            remote_account_id="37c86c4f-5370-466b-a36b-40b533f6cf31",
            snapshot_id=snapshot.id,
        )

        with pytest.raises(AccountRepairError, match="mapping history"):
            AccountRepairService(session).canonicalise_and_merge(
                issuer="Qik", raw_references=["*2197"]
            )

    def test_creates_audit_event(self, session: Session) -> None:
        _make_account(session, external_reference="2197")
        dup = _make_account(session, external_reference="*2197")

        svc = AccountRepairService(session)
        result = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197", "2197"]
        )
        session.commit()

        audit_events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_kind == AuditEventKind.FINANCIAL_ACCOUNT_MERGED
            )
        ).all()
        assert len(audit_events) >= 1
        payload = audit_events[-1].payload
        assert payload is not None
        assert str(dup.id) in payload.get("merged_account_ids", [])

    def test_duplicate_deleted(self, session: Session) -> None:
        dup1 = _make_account(session, external_reference="*2197")

        svc = AccountRepairService(session)
        result = svc.canonicalise_and_merge(
            issuer="Qik", raw_references=["*2197"]
        )
        session.commit()

        # The duplicate should have been deleted
        deleted = session.get(FinancialAccount, dup1.id)
        assert deleted is None


# ── repair_qik_account tests ──────────────────────────────────────────


class TestRepairQikAccount:
    def test_full_repair_with_mapping(self, session: Session) -> None:
        _make_account(session, external_reference="*2197")
        _make_account(session, external_reference="************2197")
        _make_accounts_snapshot(session)

        svc = AccountRepairService(session)
        result = svc.repair_qik_account(
            issuer="Qik",
            raw_references=["*2197", "************2197"],
            wallet_account_id="37c86c4f-5370-466b-a36b-40b533f6cf31",
        )
        session.commit()

        assert result.survivor_account_id is not None
        assert result.merged_account_ids
        assert result.mapping_account_id is not None
        assert result.mapping_remote_id == "37c86c4f-5370-466b-a36b-40b533f6cf31"

        # Verify mapping exists
        survivor = session.get(FinancialAccount, uuid.UUID(result.survivor_account_id))
        assert survivor is not None
        mapping_svc = AccountMappingService(session)
        mapping = mapping_svc.get_active_mapping(survivor.id)
        assert mapping is not None
        assert mapping.remote_account_id == "37c86c4f-5370-466b-a36b-40b533f6cf31"

    def test_idempotent_repair(self, session: Session) -> None:
        _make_account(session, external_reference="*2197")
        _make_accounts_snapshot(session)

        svc = AccountRepairService(session)
        result1 = svc.repair_qik_account(
            issuer="Qik",
            raw_references=["*2197"],
            wallet_account_id="37c86c4f-5370-466b-a36b-40b533f6cf31",
        )
        session.commit()

        result2 = svc.repair_qik_account(
            issuer="Qik",
            raw_references=["*2197"],
            wallet_account_id="37c86c4f-5370-466b-a36b-40b533f6cf31",
        )
        session.commit()

        # Second call should not fail and mapping should remain
        assert result2.mapping_account_id is not None
        assert result2.mapping_remote_id == "37c86c4f-5370-466b-a36b-40b533f6cf31"

    def test_repair_refuses_when_no_snapshot(self, session: Session) -> None:
        _make_account(session, external_reference="*2197")

        svc = AccountRepairService(session)
        with pytest.raises(AccountRepairError, match="sync-catalog first"):
            svc.repair_qik_account(
                issuer="Qik",
                raw_references=["*2197"],
                wallet_account_id="37c86c4f-5370-466b-a36b-40b533f6cf31",
            )

    def test_repair_creates_canonical_account(self, session: Session) -> None:
        _make_account(session, external_reference="*2197")
        _make_accounts_snapshot(session)

        svc = AccountRepairService(session)
        result = svc.repair_qik_account(
            issuer="Qik",
            raw_references=["*2197"],
            wallet_account_id="37c86c4f-5370-466b-a36b-40b533f6cf31",
        )
        session.commit()

        survivor = session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.external_reference == "2197"
            )
        )
        assert survivor is not None
        assert str(survivor.id) == result.survivor_account_id


# ── integration with WalletWorkflow ingestion ─────────────────────────


class TestNormalizationInIngestion:
    def test_find_or_create_normalizes_reference(
        self, session: Session
    ) -> None:
        from wallet_v2.application.service import WalletWorkflow

        # Pre-create an account with canonical reference
        _make_account(session, external_reference="2197")

        workflow = WalletWorkflow(session)
        # This call uses the normalized reference internally
        acct = workflow._find_or_create_account(
            issuer="Qik", external_reference="*2197"
        )
        session.flush()

        assert acct.external_reference == "2197"
        accounts = session.scalars(select(FinancialAccount)).all()
        # Should have found the existing canonical account, not created a new one
        assert len(accounts) == 1

    def test_find_or_create_creates_canonical_if_missing(
        self, session: Session
    ) -> None:
        from wallet_v2.application.service import WalletWorkflow

        workflow = WalletWorkflow(session)
        acct = workflow._find_or_create_account(
            issuer="Qik", external_reference="*2197"
        )
        session.flush()

        assert acct.external_reference == "2197"
        # No *2197 account should exist
        raw = session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.external_reference == "*2197"
            )
        )
        assert raw is None

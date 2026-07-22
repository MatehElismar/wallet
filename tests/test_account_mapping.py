"""Hermetic tests for AccountMapping model and AccountMappingService.

Tests cover:
- Model creation and immutability/mutable signal
- Unique active-mapping constraint (partial index)
- Service create_mapping validation (snapshot exists, resource_kind, account
  presence, archived rejection)
- Supersede flow
- Integration with WalletWorkflow import path
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wallet_v2.application.account_mapping import (
    AccountMappingService,
    MappingError,
)
from wallet_v2.application.service import WalletWorkflow
from wallet_v2.domain.enums import (
    DocumentKind,
    IntegrationMode,
    ReconciliationOutcome,
    StatementStatus,
    TransactionDirection,
)
from wallet_v2.persistence.models import (
    AccountMapping,
    BankStatement,
    BankStatementLine,
    CatalogSyncCursor,
    CatalogSyncSnapshot,
    ExecutionRun,
    FinancialAccount,
    FinancialEvent,
    ReconciliationLink,
    StatementReviewBatch,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_account(session: Session, issuer: str = "Test Bank") -> FinancialAccount:
    acct = FinancialAccount(
        issuer=issuer,
        external_reference="acct-123",
    )
    session.add(acct)
    session.flush()
    return acct


def _make_accounts_snapshot(
    session: Session,
    *,
    items: list[dict] | None = None,
    version: int = 1,
) -> CatalogSyncSnapshot:
    if items is None:
        items = [
            {"id": "wa1", "name": "Wallet Account 1", "archived": False},
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
    cursor = session.scalar(
        select(CatalogSyncCursor).where(CatalogSyncCursor.resource_kind == "accounts")
    )
    if cursor is None:
        cursor = CatalogSyncCursor(resource_kind="accounts")
        session.add(cursor)
    cursor.current_snapshot = snap
    cursor.last_synced_at = _utcnow()
    session.flush()
    return snap


# ── model tests ───────────────────────────────────────────────────────


class TestAccountMappingModel:
    def test_table_registered(self, metadata_tables: dict[str, object]) -> None:
        table = metadata_tables.get("account_mappings")
        assert table is not None, "account_mappings table should be registered"

    def test_has_timestamped_mixin(self, metadata_tables: dict[str, object]) -> None:
        table = metadata_tables["account_mappings"]
        columns = {col.name for col in table.columns}
        assert "created_at" in columns
        assert "updated_at" in columns

    def test_can_create_mapping(self, session: Session) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)
        now = _utcnow()

        mapping = AccountMapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            validated_snapshot_id=snap.id,
            validated_snapshot_version=snap.snapshot_version,
            validated_at=now,
        )
        session.add(mapping)
        session.commit()

        assert mapping.id is not None
        assert mapping.superseded_at is None
        assert mapping.created_at is not None
        assert mapping.financial_account_id == account.id

    def test_active_mapping_partial_unique_index(self, session: Session) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)
        now = _utcnow()

        m1 = AccountMapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            validated_snapshot_id=snap.id,
            validated_snapshot_version=1,
            validated_at=now,
        )
        session.add(m1)
        session.commit()

        m2 = AccountMapping(
            financial_account_id=account.id,
            remote_account_id="wa2",
            validated_snapshot_id=snap.id,
            validated_snapshot_version=1,
            validated_at=now,
        )
        session.add(m2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_superseded_mapping_allows_new_active(self, session: Session) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)
        now = _utcnow()

        m1 = AccountMapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            validated_snapshot_id=snap.id,
            validated_snapshot_version=1,
            validated_at=now,
        )
        session.add(m1)
        session.commit()

        m1.superseded_at = now
        session.commit()

        m2 = AccountMapping(
            financial_account_id=account.id,
            remote_account_id="wa2",
            validated_snapshot_id=snap.id,
            validated_snapshot_version=1,
            validated_at=now,
        )
        session.add(m2)
        session.commit()
        assert m2.id is not None


# ── service tests ─────────────────────────────────────────────────────


class TestAccountMappingService:
    def test_create_mapping_succeeds(self, session: Session) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)

        svc = AccountMappingService(session)
        mapping = svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            snapshot_id=snap.id,
        )
        session.commit()

        assert mapping.remote_account_id == "wa1"
        assert mapping.validated_snapshot_id == snap.id
        assert mapping.validated_snapshot_version == 1
        assert mapping.validated_at is not None
        assert mapping.superseded_at is None

    def test_create_mapping_rejects_duplicate_active(self, session: Session) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)

        svc = AccountMappingService(session)
        svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            snapshot_id=snap.id,
        )
        session.commit()

        with pytest.raises(MappingError, match="already has an active mapping"):
            svc.create_mapping(
                financial_account_id=account.id,
                remote_account_id="wa2",
                snapshot_id=snap.id,
            )

    def test_get_active_mapping_returns_none_when_no_mapping(
        self, session: Session
    ) -> None:
        svc = AccountMappingService(session)
        result = svc.get_active_mapping(financial_account_id=uuid.uuid4())
        assert result is None

    def test_get_active_mapping_returns_active(self, session: Session) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)

        svc = AccountMappingService(session)
        mapping = svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            snapshot_id=snap.id,
        )
        session.commit()

        active = svc.get_active_mapping(account.id)
        assert active is not None
        assert active.id == mapping.id

    def test_catalog_refresh_makes_prior_mapping_ineligible_for_import(
        self, session: Session
    ) -> None:
        account = _make_account(session)
        first_snapshot = _make_accounts_snapshot(session, version=1)
        svc = AccountMappingService(session)
        svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            snapshot_id=first_snapshot.id,
        )
        _make_accounts_snapshot(session, version=2)
        assert svc.get_active_mapping(account.id) is None

    def test_get_active_mapping_excludes_superseded(self, session: Session) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)

        svc = AccountMappingService(session)
        svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            snapshot_id=snap.id,
        )
        session.commit()

        svc.supersede_mapping(account.id)
        session.commit()

        active = svc.get_active_mapping(account.id)
        assert active is None

    def test_supersede_then_create_new_mapping(self, session: Session) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)

        svc = AccountMappingService(session)
        svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            snapshot_id=snap.id,
        )
        session.commit()

        svc.supersede_mapping(account.id)
        session.commit()

        snap2 = _make_accounts_snapshot(
            session,
            items=[{"id": "wa2", "name": "New Wallet", "archived": False}],
            version=2,
        )
        m2 = svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa2",
            snapshot_id=snap2.id,
        )
        session.commit()

        assert m2.remote_account_id == "wa2"
        active = svc.get_active_mapping(account.id)
        assert active is not None
        assert active.id == m2.id

    def test_supersede_mapping_returns_none_when_none(
        self, session: Session
    ) -> None:
        svc = AccountMappingService(session)
        result = svc.supersede_mapping(financial_account_id=uuid.uuid4())
        assert result is None

    def test_create_mapping_rejects_blank_remote_id(
        self, session: Session
    ) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)
        svc = AccountMappingService(session)

        with pytest.raises(MappingError, match="must not be blank"):
            svc.create_mapping(
                financial_account_id=account.id,
                remote_account_id="  ",
                snapshot_id=snap.id,
            )

    def test_create_mapping_rejects_missing_snapshot(
        self, session: Session
    ) -> None:
        account = _make_account(session)
        svc = AccountMappingService(session)

        with pytest.raises(MappingError, match="not found"):
            svc.create_mapping(
                financial_account_id=account.id,
                remote_account_id="wa1",
                snapshot_id=uuid.uuid4(),
            )

    def test_create_mapping_rejects_non_account_snapshot(
        self, session: Session
    ) -> None:
        account = _make_account(session)
        snap = CatalogSyncSnapshot(
            resource_kind="categories",
            snapshot_version=1,
            catalog_data={"items": [{"id": "c1"}]},
        )
        session.add(snap)
        session.flush()
        svc = AccountMappingService(session)

        with pytest.raises(MappingError, match="expected 'accounts'"):
            svc.create_mapping(
                financial_account_id=account.id,
                remote_account_id="c1",
                snapshot_id=snap.id,
            )

    def test_create_mapping_rejects_unknown_account_in_snapshot(
        self, session: Session
    ) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(
            session, items=[{"id": "wa1", "name": "Only One", "archived": False}]
        )
        svc = AccountMappingService(session)

        with pytest.raises(MappingError, match="not found in snapshot"):
            svc.create_mapping(
                financial_account_id=account.id,
                remote_account_id="nonexistent",
                snapshot_id=snap.id,
            )

    def test_create_mapping_rejects_archived_account(
        self, session: Session
    ) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(
            session,
            items=[{"id": "archived1", "name": "Old Account", "archived": True}],
        )
        svc = AccountMappingService(session)

        with pytest.raises(MappingError, match="archived"):
            svc.create_mapping(
                financial_account_id=account.id,
                remote_account_id="archived1",
                snapshot_id=snap.id,
            )

    def test_create_mapping_rejects_empty_snapshot_items(
        self, session: Session
    ) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session, items=[])
        svc = AccountMappingService(session)

        with pytest.raises(MappingError, match="contains no accounts"):
            svc.create_mapping(
                financial_account_id=account.id,
                remote_account_id="wa1",
                snapshot_id=snap.id,
            )

    def test_get_active_remote_account_id_returns_id(
        self, session: Session
    ) -> None:
        account = _make_account(session)
        snap = _make_accounts_snapshot(session)
        svc = AccountMappingService(session)
        svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            snapshot_id=snap.id,
        )
        session.commit()

        remote_id = svc.get_active_remote_account_id(account.id)
        assert remote_id == "wa1"

    def test_get_active_remote_account_id_raises_when_unmapped(
        self, session: Session
    ) -> None:
        svc = AccountMappingService(session)
        with pytest.raises(MappingError, match="no active validated mapping"):
            svc.get_active_remote_account_id(financial_account_id=uuid.uuid4())


# ── integration with WalletWorkflow import path ───────────────────────


class TestWalletWorkflowImportUsesValidatedMapping:
    def test_import_rejects_unmapped_account(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(
            mode=IntegrationMode.DRY_RUN, trigger="test", label="test-mapping"
        )

        account = _make_account(session)
        event = self._make_fake_event(session, run, account)

        with pytest.raises(ValueError, match="validated mapping"):
            workflow.import_approved_financial_event(
                run=run, event=event, wallet=None
            )

    def test_import_succeeds_with_validated_mapping(
        self, session: Session
    ) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(
            mode=IntegrationMode.DRY_RUN, trigger="test", label="test-mapping-ok"
        )

        account = _make_account(session)
        snap = _make_accounts_snapshot(session)
        event = self._make_fake_event(session, run, account)

        svc = AccountMappingService(session)
        svc.create_mapping(
            financial_account_id=account.id,
            remote_account_id="wa1",
            snapshot_id=snap.id,
        )
        session.flush()

        command = workflow.import_approved_financial_event(
            run=run, event=event, wallet=None
        )
        session.flush()

        assert command.financial_event_id == event.id
        assert command.payload.get("accountReference") == "wa1"

    def _make_fake_event(
        self,
        session: Session,
        run: ExecutionRun,
        account: FinancialAccount,
    ) -> FinancialEvent:
        from wallet_v2.persistence.models import (
            Inbox,
            ProcessingAttempt,
            SourceMessage,
        )
        from wallet_v2.domain.enums import (
            AttemptStatus,
            MailboxSourceStatus,
            SourceMessageStatus,
        )

        inbox = Inbox(
            provider="test",
            account_fingerprint="a" * 64,
            folder="INBOX",
            status=MailboxSourceStatus.ACTIVE,
        )
        session.add(inbox)
        session.flush()
        sm = SourceMessage(
            execution_run_id=run.id,
            inbox_id=inbox.id,
            uid_validity=1,
            message_uid=1,
            content_hash="0" * 64,
            status=SourceMessageStatus.RECEIVED,
            received_at=_utcnow(),
        )
        session.add(sm)
        session.flush()
        attempt = ProcessingAttempt(
            execution_run_id=run.id,
            source_message_id=sm.id,
            attempt_index=1,
            idempotency_key="attempt-mapping-test",
            status=AttemptStatus.SUCCEEDED,
        )
        session.add(attempt)
        session.flush()
        statement = BankStatement(
            source_message_id=sm.id,
            processing_attempt_id=attempt.id,
            account_id=account.id,
            statement_version=1,
            status=StatementStatus.APPROVED,
            document_fingerprint="f" * 64,
            currency="USD",
        )
        session.add(statement)
        session.flush()
        line = BankStatementLine(
            statement_id=statement.id,
            line_index=1,
            line_fingerprint="lf" + "0" * 62,
            direction=TransactionDirection.DEBIT,
            amount_minor=1000,
            currency="USD",
            merchant="Test",
            event_status="posted",
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
            status="posted",
            direction=TransactionDirection.DEBIT,
            amount_minor=1000,
            currency="USD",
            merchant="Test",
        )
        session.add(event)
        session.flush()
        return event


class TestFuzzyAccountMatching:
    """Test fuzzy account catalog inferencing and auto-mapping."""

    def test_score_account_match(self) -> None:
        from wallet_v2.application.account_mapping import score_account_match

        # Issuer + last 4 digits match
        assert score_account_match("Popular", "CC 2727", "Popular CC 2727") == 1.0
        assert score_account_match("Banco Santa Cruz", "Visa 5678", "Santa Cruz Visa 5678") >= 0.8
        assert score_account_match("BHD", "Debito 1234", "BHD Debito 1234") == 1.0

        # Unrelated account
        assert score_account_match("Popular", "2727", "Qik Credit Card 2197") == 0.0

    def test_auto_map_if_matching(self, session: Session) -> None:
        from wallet_v2.application.account_mapping import AccountMappingService

        # 1. Create a catalog snapshot containing "Popular CC 2727"
        snapshot = CatalogSyncSnapshot(
            resource_kind="accounts",
            snapshot_version=1,
            catalog_data={
                "items": [
                    {"id": "wa-popular-2727", "name": "Popular CC 2727", "archived": False},
                    {"id": "wa-bhd-1234", "name": "BHD Debito 1234", "archived": False},
                ]
            },
        )
        session.add(snapshot)
        session.flush()
        cursor = CatalogSyncCursor(
            resource_kind="accounts",
            current_snapshot_id=snapshot.id,
            last_synced_at=_utcnow(),
        )
        session.add(cursor)
        session.flush()

        # 2. Instantiate workflow and create financial account for Popular CC 2727
        wf = WalletWorkflow(session)
        acct = wf._find_or_create_account(issuer="Popular", external_reference="CC 2727")
        session.commit()

        # 3. Assert active mapping was created automatically
        mapping_svc = AccountMappingService(session)
        mapping = mapping_svc.get_active_mapping(acct.id)
        assert mapping is not None
        assert mapping.remote_account_id == "wa-popular-2727"


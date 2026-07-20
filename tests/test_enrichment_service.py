"""Hermetic tests for Phase B deterministic enrichment service.

Covers:
- Candidate research preview is advisory-only and can never finalize/import.
- Canonical-event enrichment decision ranking (exact recurrence, merchant
  history, majority vote, ties/weak -> no_recommendation).
- Profile gate (once, persist non-secret metadata), bounded query inputs,
  integrity hash, bounded evidence.
- Catalog validation at decision and finalization time; stale/missing
  catalog item fails closed.
- No numeric confidence; transparent evidence grades only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from wallet_v2.application.account_mapping import AccountMappingService
from wallet_v2.application.contracts_mcp import (
    McpCategory,
    McpClientProfile,
    McpLabel,
    McpReadOnlyClient,
    McpRecord,
    McpRecordsResult,
    McpResponseMeta,
)
from wallet_v2.application.enrichment import (
    CandidateResearchPreview,
    EnrichmentDecision,
    EnrichmentProposal,
    EnrichmentService,
    _amount_value_to_minor,
    _MAX_RECORDS_PER_QUERY,
    compute_integrity_hash,
)
from wallet_v2.domain.enums import TransactionDirection
from wallet_v2.persistence.models import (
    AccountMapping,
    CatalogSyncSnapshot,
    FinancialAccount,
    FinancialEvent,
    McpProfileSnapshot,
    TransactionCandidate,
)
from wallet_v2.persistence.models.mcp import AdvisoryResearch
from wallet_v2.persistence.models.wallet_catalog import CatalogSyncCursor


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── fake read-only MCP client ────────────────────────────────────────────


class FakeReadOnlyMcp(McpReadOnlyClient):
    """In-memory read-only MCP stand-in. No network, no writes."""

    def __init__(
        self,
        *,
        sync_state: str = "complete",
        scopes: tuple[str, ...] = (
            "accounts.read",
            "records.read",
            "budgets.read",
            "record_rules.read",
        ),
        records_by_account: dict[str, list[McpRecord]] | None = None,
        records_error: bool = False,
        records_page_size: int = 200,
    ) -> None:
        self._sync_state = sync_state
        self._scopes = scopes
        self._records_by_account = records_by_account or {}
        self._records_error = records_error
        self._records_page_size = records_page_size
        self._profile_calls = 0
        self._records_calls = 0
        self._last_meta = McpResponseMeta(
            synced_at="2026-07-19T10:00:00Z",
            rate_limit_remaining=299,
            rate_limit_capacity=300,
            rate_limit_refill_per_minute=60,
        )

    @property
    def last_response_meta(self) -> McpResponseMeta:
        return self._last_meta

    @property
    def profile_validated(self) -> bool:
        return self._profile_calls > 0

    def get_client_profile(self) -> McpClientProfile:
        self._profile_calls += 1
        if self._sync_state != "complete":
            raise ValueError(f"syncState is {self._sync_state!r}")
        return McpClientProfile(
            sync_state=self._sync_state,
            granted_scopes=self._scopes,
            synced_at=self._last_meta.synced_at,
        )

    def get_records(
        self,
        *,
        account_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> McpRecordsResult:
        self._records_calls += 1
        if self._records_error:
            raise ValueError("forced MCP error")
        records = list(self._records_by_account.get(account_id, []))
        page_size = min(limit, self._records_page_size)
        page = records[offset : offset + page_size]
        next_offset = (
            offset + len(page) if offset + len(page) < len(records) else None
        )
        return McpRecordsResult(
            records=tuple(page),
            total=len(records),
            offset=offset,
            limit=page_size,
            next_offset=next_offset,
        )

    def get_records_aggregation(self, **_kw: object) -> object:
        raise AssertionError("not used by enrichment service")

    def get_budgets(self, **_kw: object) -> object:
        raise AssertionError("not used by enrichment service")

    def get_entity(self, **_kw: object) -> object:
        raise AssertionError("not used by enrichment service")


class BypassReadOnlyMcp(McpReadOnlyClient):
    """Injects a profile that bypasses the adapter's own gate.

    Models a malicious or buggy client that returns a profile with an
    incomplete sync state (or without ``records.read``) *without raising*, as
    the adapter would. The enrichment service must still fail closed.
    """

    def __init__(
        self,
        *,
        sync_state: str = "incomplete",
        scopes: tuple[str, ...] = ("accounts.read",),
    ) -> None:
        self._sync_state = sync_state
        self._scopes = scopes
        self._records_calls = 0
        self._last_meta = McpResponseMeta(synced_at="2026-07-19T10:00:00Z")

    @property
    def last_response_meta(self) -> McpResponseMeta:
        return self._last_meta

    @property
    def profile_validated(self) -> bool:
        return True

    def get_client_profile(self) -> McpClientProfile:
        # Intentionally does NOT raise, simulating an adapter bypass.
        return McpClientProfile(
            sync_state=self._sync_state,
            granted_scopes=self._scopes,
            synced_at=self._last_meta.synced_at,
        )

    def get_records(self, **_kw: object) -> McpRecordsResult:
        raise AssertionError("must not be reached when profile gate fails")

    def get_records_aggregation(self, **_kw: object) -> object:
        raise AssertionError("not used by enrichment service")

    def get_budgets(self, **_kw: object) -> object:
        raise AssertionError("not used by enrichment service")

    def get_entity(self, **_kw: object) -> object:
        raise AssertionError("not used by enrichment service")


def _record(
    rec_id: str,
    account_id: str,
    *,
    amount: float,
    currency: str = "USD",
    record_date: str = "2026-06-15",
    counter_party: str | None = "Online Store",
    category_id: str | None = "cat_1",
    labels: tuple[str, ...] = (),
    payment_type: str | None = "debit_card",
) -> McpRecord:
    return McpRecord(
        id=rec_id,
        account_id=account_id,
        amount_value=amount,
        currency=currency,
        record_date=record_date,
        counter_party=counter_party,
        category=McpCategory(id=category_id, name="X") if category_id else None,
        labels=tuple(McpLabel(id=l, name=l) for l in labels),
        payment_type=payment_type,
        record_state="cleared",
    )


# ── helpers to build local state ────────────────────────────────────────


def _make_financial_account(session) -> FinancialAccount:
    acct = FinancialAccount(issuer="Test Bank", external_reference="acct-123")
    session.add(acct)
    session.flush()
    return acct


def _make_accounts_snapshot(session, items=None, version=1) -> CatalogSyncSnapshot:
    if items is None:
        items = [{"id": "wa1", "name": "Wallet Account 1", "archived": False}]
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
        select(CatalogSyncCursor).where(
            CatalogSyncCursor.resource_kind == "accounts"
        )
    )
    if cursor is None:
        cursor = CatalogSyncCursor(resource_kind="accounts")
    cursor.resource_kind = "accounts"
    cursor.current_snapshot = snap
    cursor.last_synced_at = _utcnow()
    session.add(cursor)
    session.flush()
    return snap


def _make_categories_snapshot(session, items=None, version=1) -> CatalogSyncSnapshot:
    if items is None:
        items = [
            {"id": "cat_1", "name": "Groceries", "archived": False},
            {"id": "cat_2", "name": "Coffee", "archived": False},
        ]
    snap = CatalogSyncSnapshot(
        resource_kind="categories",
        snapshot_version=version,
        catalog_data={
            "version": 1, "resource_kind": "categories",
            "snapshot_version": version, "item_count": len(items), "items": items,
        },
    )
    session.add(snap)
    session.flush()
    cursor = session.scalar(
        select(CatalogSyncCursor).where(
            CatalogSyncCursor.resource_kind == "categories"
        )
    )
    if cursor is None:
        cursor = CatalogSyncCursor(resource_kind="categories")
    cursor.resource_kind = "categories"
    cursor.current_snapshot = snap
    session.add(cursor)
    session.flush()
    return snap


def _make_labels_snapshot(session, items=None, version=1) -> CatalogSyncSnapshot:
    if items is None:
        items = [
            {"id": "lbl_1", "name": "Food", "archived": False},
            {"id": "lbl_2", "name": "Weekly", "archived": False},
        ]
    snap = CatalogSyncSnapshot(
        resource_kind="labels",
        snapshot_version=version,
        catalog_data={
            "version": 1, "resource_kind": "labels",
            "snapshot_version": version, "item_count": len(items), "items": items,
        },
    )
    session.add(snap)
    session.flush()
    cursor = session.scalar(
        select(CatalogSyncCursor).where(
            CatalogSyncCursor.resource_kind == "labels"
        )
    )
    if cursor is None:
        cursor = CatalogSyncCursor(resource_kind="labels")
    cursor.resource_kind = "labels"
    cursor.current_snapshot = snap
    session.add(cursor)
    session.flush()
    return snap


def _map(session, account_id, remote_id="wa1", version=1) -> None:
    snap = _make_accounts_snapshot(session, version=version)
    svc = AccountMappingService(session)
    svc.create_mapping(
        financial_account_id=account_id,
        remote_account_id=remote_id,
        snapshot_id=snap.id,
    )
    session.flush()


def _seeded_session(session) -> FinancialAccount:
    account = _make_financial_account(session)
    _map(session, account.id)
    _make_categories_snapshot(session)
    _make_labels_snapshot(session)
    return account


def _make_event(session, account) -> FinancialEvent:
    from wallet_v2.persistence.models import (
        Inbox,
        ProcessingAttempt,
        SourceMessage,
        ExecutionRun,
        BankStatement,
        BankStatementLine,
        ReconciliationLink,
    )
    from wallet_v2.domain.enums import (
        AttemptStatus,
        MailboxSourceStatus,
        SourceMessageStatus,
        StatementStatus,
        ReconciliationOutcome,
    )

    run = ExecutionRun(mode="dry_run", trigger="test", label="enr-test",
                       started_at=_utcnow())
    session.add(run)
    session.flush()

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
        idempotency_key=f"enr-attempt-{uuid.uuid4().hex}",
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
        amount_minor=4230,
        currency="USD",
        merchant="Online Store",
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
        amount_minor=4230,
        currency="USD",
        merchant="Online Store",
        transaction_date=date(2026, 7, 18),
    )
    session.add(event)
    session.flush()
    return event


def _make_candidate(session, account) -> TransactionCandidate:
    from wallet_v2.persistence.models import (
        Inbox,
        ProcessingAttempt,
        SourceMessage,
        ExecutionRun,
    )
    from wallet_v2.domain.enums import (
        AttemptStatus,
        MailboxSourceStatus,
        SourceMessageStatus,
    )

    run = ExecutionRun(mode="dry_run", trigger="test", label="enr-cand",
                       started_at=_utcnow())
    session.add(run)
    session.flush()
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
        idempotency_key=f"enr-cand-{uuid.uuid4().hex}",
        status=AttemptStatus.SUCCEEDED,
    )
    session.add(attempt)
    session.flush()
    candidate = TransactionCandidate(
        source_message_id=sm.id,
        attempt_id=attempt.id,
        candidate_version=1,
        status="proposed",
        direction="debit",
        amount_minor=4230,
        currency="USD",
        merchant="Online Store",
        transaction_date=date(2026, 7, 18),
    )
    candidate.account_id = account.id
    session.add(candidate)
    session.flush()
    return candidate


# ── integrity hash ──────────────────────────────────────────────────────


class TestIntegrityHash:
    def test_deterministic(self) -> None:
        h1 = compute_integrity_hash(query_inputs={"a": 1}, evidence_ids=["x", "y"])
        h2 = compute_integrity_hash(query_inputs={"a": 1}, evidence_ids=["y", "x"])
        assert h1 == h2
        assert len(h1) == 64

    def test_differs_on_inputs(self) -> None:
        h1 = compute_integrity_hash(query_inputs={"a": 1}, evidence_ids=[])
        h2 = compute_integrity_hash(query_inputs={"a": 2}, evidence_ids=[])
        assert h1 != h2


# ── candidate research preview ──────────────────────────────────────────


class TestCandidateResearchPreview:
    def test_preview_is_never_finalizable(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        candidate = _make_candidate(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        preview = svc.build_candidate_preview(candidate)
        assert isinstance(preview, CandidateResearchPreview)
        assert preview.is_finalizable is False

    def test_preview_recommends_on_exact_recurrence(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        candidate = _make_candidate(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        preview = svc.build_candidate_preview(candidate)
        assert preview.recommendation is True
        assert preview.evidence_grade == "exact_recurrence"
        assert preview.selected_account_id == "wa1"
        assert preview.selected_category_id == "cat_1"

    def test_preview_no_recommendation_without_mapping(self, session) -> None:
        account = _make_financial_account(session)
        candidate = _make_candidate(session, account)
        mcp = FakeReadOnlyMcp()
        svc = EnrichmentService(session, mcp)
        preview = svc.build_candidate_preview(candidate)
        assert preview.recommendation is False
        assert preview.evidence_grade == "no_recommendation"

    def test_preview_persists_advisory_research(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        candidate = _make_candidate(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        preview = svc.build_candidate_preview(candidate)
        research = session.scalar(
            select(AdvisoryResearch).where(
                AdvisoryResearch.candidate_id == candidate.id
            )
        )
        assert research is not None
        assert research.integrity_hash == preview.integrity_hash
        assert research.evidence_grade == preview.evidence_grade


# ── canonical-event enrichment decision ─────────────────────────────────


class TestEventEnrichmentDecision:
    def _seeded_session(self, session) -> FinancialAccount:
        account = _make_financial_account(session)
        _map(session, account.id)
        _make_categories_snapshot(session)
        _make_labels_snapshot(session)
        return account

    def test_exact_recurrence_recommends(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert isinstance(decision, EnrichmentDecision)
        assert decision.evidence_grade == "exact_recurrence"
        assert decision.selected_account_id == "wa1"
        assert decision.selected_category_id == "cat_1"
        assert decision.finalized is False
        assert decision.confidence is None

    def test_merchant_history_majority_vote(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={
                "wa1": [
                    _record("r1", "wa1", amount=-99.0, counter_party="Online Store LLC",
                            category_id="cat_1", labels=("lbl_1",), payment_type="card"),
                    _record("r2", "wa1", amount=-10.0, counter_party="Online Store LLC",
                            category_id="cat_1", labels=("lbl_1",), payment_type="card"),
                    _record("r3", "wa1", amount=-5.0, counter_party="Online Store LLC",
                            category_id="cat_2", labels=("lbl_1",), payment_type="card"),
                ]
            }
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "merchant_history"
        assert decision.selected_category_id == "cat_1"
        assert decision.selected_label_ids == ["lbl_1"]
        assert decision.selected_payment_type == "card"

    def test_tied_category_vote_no_recommendation(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={
                "wa1": [
                    _record("r1", "wa1", amount=-99.0, counter_party="Online Store",
                            category_id="cat_1"),
                    _record("r2", "wa1", amount=-10.0, counter_party="Online Store",
                            category_id="cat_2"),
                ]
            }
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "no_recommendation"
        assert decision.selected_category_id is None
        assert decision.selected_account_id is None

    def test_no_mapping_no_recommendation(self, session) -> None:
        account = _make_financial_account(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp()
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "no_recommendation"
        assert decision.selected_account_id is None

    def test_mcp_error_no_recommendation(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(records_error=True)
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "no_recommendation"

    def test_stale_profile_sync_no_recommendation(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(sync_state="incomplete")
        svc = EnrichmentService(session, mcp)
        # Service fails closed: persisted no_recommendation, does not raise.
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "no_recommendation"
        assert decision.selected_account_id is None

    def test_bypass_adapter_incomplete_sync_persists_no_rec(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = BypassReadOnlyMcp(sync_state="incomplete")
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "no_recommendation"
        # The profile snapshot was still persisted (audit), but no query ran.
        assert mcp._records_calls == 0

    def test_bypass_adapter_missing_records_read_persists_no_rec(
        self, session
    ) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = BypassReadOnlyMcp(
            sync_state="complete", scopes=("accounts.read", "budgets.read")
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "no_recommendation"
        assert mcp._records_calls == 0

    def test_candidate_preview_bypass_persists_no_rec(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        candidate = _make_candidate(session, account)
        mcp = BypassReadOnlyMcp(sync_state="incomplete")
        svc = EnrichmentService(session, mcp)
        preview = svc.build_candidate_preview(candidate)
        assert preview.recommendation is False
        assert preview.evidence_grade == "no_recommendation"

    def test_only_context_records_context_only_grade(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={
                "wa1": [
                    _record("r1", "wa1", amount=-999.0, counter_party="Unrelated Co",
                            category_id="cat_1"),
                ]
            }
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        # Context was present but unrelated — a transparent context_only
        # grade, distinct from no_recommendation (no history returned).
        assert decision.evidence_grade == "context_only"
        assert decision.selected_account_id is None

    def test_no_records_at_all_is_no_recommendation(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(records_by_account={"wa1": []})
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "no_recommendation"
        assert decision.selected_account_id is None

    def test_exact_recurrence_vote_ignores_weaker_history(self, session) -> None:
        # An exact-recurrence row (cat_1 / pay_a) must not be contaminated by
        # weaker merchant-history rows that share the merchant but vote for a
        # different category/payment.
        account = _seeded_session(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={
                "wa1": [
                    _record("r1", "wa1", amount=-42.30, counter_party="Online Store",
                            category_id="cat_1", payment_type="pay_a"),
                    _record("r2", "wa1", amount=-19.99, counter_party="Online Store LLC",
                            category_id="cat_2", payment_type="pay_b"),
                    _record("r3", "wa1", amount=-5.00, counter_party="Online Store LLC",
                            category_id="cat_2", payment_type="pay_b"),
                ]
            }
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "exact_recurrence"
        assert decision.selected_category_id == "cat_1"
        assert decision.selected_payment_type == "pay_a"


# ── pagination (bounded via next_offset) ─────────────────────────────────


class TestPagination:
    def test_paginates_through_next_offset(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        # 120 exact-match records across pages of 50 -> 3 get_records calls.
        records = [
            _record(f"r{i}", "wa1", amount=-42.30) for i in range(120)
        ]
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": records}, records_page_size=50
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert mcp._records_calls == 3
        assert decision.evidence_grade == "exact_recurrence"

    def test_single_page_when_under_limit(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        records = [
            _record(f"r{i}", "wa1", amount=-42.30) for i in range(40)
        ]
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": records}, records_page_size=50
        )
        svc = EnrichmentService(session, mcp)
        svc.build_event_decision(event, version=1)
        assert mcp._records_calls == 1

    def test_result_capped_at_max_records(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        records = [
            _record(f"r{i}", "wa1", amount=-42.30) for i in range(500)
        ]
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": records}, records_page_size=50
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        # Pages of 50 are merged until the 200-record cap is reached (4 pages),
        # then fetching stops well before all 500 records are pulled.
        assert mcp._records_calls == 4
        assert decision.evidence_grade == "exact_recurrence"
        assert _MAX_RECORDS_PER_QUERY == 200


# ── Decimal amount comparison (no float multiplication) ─────────────────


class TestDecimalAmounts:
    def test_amount_value_to_minor_exact(self) -> None:
        assert _amount_value_to_minor(-42.30) == -4230
        assert _amount_value_to_minor(19.99) == 1999
        assert _amount_value_to_minor(0.0) == 0

    def test_amount_value_to_minor_avoids_float_error(self) -> None:
        # Binary float: 2.675 * 100 == 267.4999... (rounds to 267).
        # Decimal is exact: 2.675 -> 267.5 -> 268.
        assert _amount_value_to_minor(2.675) == 268
        assert _amount_value_to_minor(-2.675) == -268

    def test_exact_recurrence_uses_decimal_not_float(self, session) -> None:
        account = _seeded_session(session)
        event = _make_event(session, account)
        # 2.675 USD debit == 268 minor. A binary-float comparison would yield
        # 267 and miss the exact recurrence (falling back to merchant_history).
        event.amount_minor = 268
        event.currency = "USD"
        event.merchant = "Online Store"
        event.transaction_date = date(2026, 7, 18)
        session.flush()
        mcp = FakeReadOnlyMcp(
            records_by_account={
                "wa1": [
                    _record("r1", "wa1", amount=-2.675,
                            counter_party="Online Store"),
                ]
            }
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "exact_recurrence"
        assert decision.selected_category_id == "cat_1"


# ── catalog validation / finalization ───────────────────────────────────


class TestFinalization:
    def test_finalize_revalidates_current_catalog(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        _make_categories_snapshot(session)
        _make_labels_snapshot(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        finalized = svc.finalize_decision(event, version=1)
        assert finalized.finalized is True
        assert finalized.id == decision.id

    def test_archived_category_blocks_at_build_time(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        _make_categories_snapshot(
            session,
            items=[{"id": "cat_1", "name": "Groceries", "archived": True}],
        )
        _make_labels_snapshot(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        # Catalog validation at decision time fails closed to no_recommendation.
        assert decision.evidence_grade == "no_recommendation"
        assert decision.selected_category_id is None
        with pytest.raises(ValueError, match="cannot finalize"):
            svc.finalize_decision(event, version=1)

    def test_finalize_blocks_on_archived_account(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        _make_categories_snapshot(session)
        _make_labels_snapshot(session)
        # Advance the accounts catalog so the mapped account is archived.
        _make_accounts_snapshot(
            session,
            items=[{"id": "wa1", "name": "Wallet", "archived": True}],
            version=2,
        )
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        assert decision.evidence_grade == "no_recommendation"
        with pytest.raises(ValueError, match="cannot finalize"):
            svc.finalize_decision(event, version=1)

    def test_cannot_finalize_no_recommendation(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        _make_categories_snapshot(session)
        _make_labels_snapshot(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(records_error=True)
        svc = EnrichmentService(session, mcp)
        svc.build_event_decision(event, version=1)
        with pytest.raises(ValueError, match="cannot finalize"):
            svc.finalize_decision(event, version=1)

    def test_decision_versioning_unique(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        _make_categories_snapshot(session)
        _make_labels_snapshot(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        svc.build_event_decision(event, version=1)
        svc.build_event_decision(event, version=2)
        dup = EnrichmentDecision(
            financial_event_id=event.id,
            version=1,
            evidence_grade="no_recommendation",
        )
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ── profile gate / bounded query ────────────────────────────────────────


class TestProfileGate:
    def test_profile_called_once_and_persisted(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        _make_categories_snapshot(session)
        _make_labels_snapshot(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        svc.build_event_decision(event, version=1)
        svc.build_event_decision(event, version=2)
        assert mcp._profile_calls == 1
        snap = session.scalar(select(McpProfileSnapshot))
        assert snap is not None
        assert snap.sync_state == "complete"
        assert "records.read" in snap.granted_scopes
        assert snap.rate_limit_metadata is not None

    def test_query_inputs_are_bounded(self, session) -> None:
        account = _make_financial_account(session)
        _map(session, account.id)
        _make_categories_snapshot(session)
        _make_labels_snapshot(session)
        event = _make_event(session, account)
        mcp = FakeReadOnlyMcp(
            records_by_account={"wa1": [_record("r1", "wa1", amount=-42.30)]}
        )
        svc = EnrichmentService(session, mcp)
        decision = svc.build_event_decision(event, version=1)
        q = decision.query_inputs
        assert q["signed_amount_minor"] == -4230
        assert q["currency"] == "USD"
        assert q["remote_account_id"] == "wa1"
        assert q["bound"]["max_records"] == 200
        assert "merchant" in q

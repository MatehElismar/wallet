"""Hermetic API tests for Phase C operator review surfaces.

Covers candidate advisory research (read-only, never finalizable) and event
enrichment decisions (generate / override / finalize / dry-run preview) with
no Wallet write and no real network. Override creates a new immutable version
and validates against the current REST catalog snapshots; finalization and the
dry-run payload preview are gated on a finalized, catalog-valid decision.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from wallet_v2.api.app import create_test_app
from wallet_v2.application import AccountMappingService, WalletWorkflow
from wallet_v2.application.contracts_mcp import (
    McpCategory,
    McpClientProfile,
    McpLabel,
    McpReadOnlyClient,
    McpRecord,
    McpRecordsResult,
    McpResponseMeta,
)
from wallet_v2.domain.enums import IntegrationMode, TransactionDirection
from wallet_v2.persistence.base import Base
from wallet_v2.persistence.models import CatalogSyncCursor, CatalogSyncSnapshot
from wallet_v2.persistence.models.mcp import AdvisoryResearch, EnrichmentDecision
from wallet_v2.persistence.models.reconciliation import FinancialEvent


def _now() -> datetime:
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def client() -> TestClient:
    app = create_test_app()
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


class FakeReadOnlyMcp(McpReadOnlyClient):
    """In-memory read-only MCP stand-in. No network, no writes."""

    def __init__(
        self,
        *,
        sync_state: str = "complete",
        records: list[McpRecord] | None = None,
    ) -> None:
        self._sync_state = sync_state
        self._records = records or []
        self._meta = McpResponseMeta(
            synced_at="2026-07-19T10:00:00Z",
            rate_limit_remaining=299,
            rate_limit_capacity=300,
            rate_limit_refill_per_minute=60,
        )

    @property
    def last_response_meta(self) -> McpResponseMeta:
        return self._meta

    @property
    def profile_validated(self) -> bool:
        return True

    def get_client_profile(self) -> McpClientProfile:
        if self._sync_state != "complete":
            raise ValueError(f"syncState is {self._sync_state!r}")
        return McpClientProfile(
            sync_state=self._sync_state,
            granted_scopes=("accounts.read", "records.read"),
            synced_at=self._meta.synced_at,
        )

    def get_records(self, **_: object) -> McpRecordsResult:
        return McpRecordsResult(records=tuple(self._records))


def _ingest_notification(client: TestClient, *, merchant: str, amount: int, account_reference: str):
    factory = client.app.state.session_factory
    with factory() as session:
        workflow = WalletWorkflow(session, now=_now)
        run = workflow.start_run(
            mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-notif"
        )
        from wallet_v2.application.contracts import (
            ExtractedTransaction,
            ExtractionResult,
            MailboxMessage,
        )

        class _Extractor:
            def extract(self, _msg: object) -> ExtractionResult:
                return ExtractionResult(
                    is_transaction=True,
                    transaction=ExtractedTransaction(
                        TransactionDirection.DEBIT, amount, "USD",
                        merchant=merchant, issuer="Qik",
                        account_reference=account_reference,
                    ),
                    raw_response={}, structured_output={}, model_id="test",
                )

        workflow.ingest_and_extract(
            run=run,
            message=MailboxMessage(
                provider="imap", account_fingerprint="a" * 64,
                folder="INBOX", uid_validity=7, message_uid=700,
                sender="alerts@test.local", recipient="wallet@test.local",
                subject="Notification", message_id_header="<notif-700@test.local>",
                received_at=_now(), body_text="Notification.",
            ),
            extractor=_Extractor(),
        )
        session.commit()
        from wallet_v2.persistence.models import TransactionCandidate
        cand = session.scalars(select(TransactionCandidate)).one()
        account_id = cand.observation.account_id
        candidate_id = cand.id
    return candidate_id, account_id


def _seed_catalog(session, kind: str, items: list[dict]) -> None:
    snap = CatalogSyncSnapshot(
        resource_kind=kind,
        snapshot_version=1,
        catalog_data={
            "version": 1, "resource_kind": kind,
            "snapshot_version": 1, "item_count": len(items), "items": items,
        },
    )
    session.add(snap)
    session.flush()
    session.add(
        CatalogSyncCursor(
            resource_kind=kind, current_snapshot=snap, last_synced_at=_now()
        )
    )
    session.flush()


def _setup_event(client: TestClient) -> str:
    """Create a canonical FinancialEvent via the existing approve path.

    No mapping or catalog snapshot is required for event creation.
    """
    factory = client.app.state.session_factory
    with factory() as session:
        workflow = WalletWorkflow(session, now=_now)
        run = workflow.start_run(
            mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-event"
        )
        from wallet_v2.application.contracts import (
            ExtractedStatement,
            ExtractedTransaction,
            ExtractionResult,
            MailboxMessage,
        )
        from wallet_v2.domain.enums import ReconciliationOutcome

        message = MailboxMessage(
            provider="imap", account_fingerprint="a" * 64,
            folder="INBOX", uid_validity=7, message_uid=701,
            sender="alerts@test.local", recipient="wallet@test.local",
            subject="Statement", message_id_header="<stmt-701@test.local>",
            received_at=_now(), body_text="Statement.",
        )

        class _Extractor:
            def extract(self, _msg: object) -> ExtractionResult:
                return ExtractionResult(
                    is_transaction=True,
                    transaction=ExtractedTransaction(
                        TransactionDirection.DEBIT, 750, "USD", merchant="Cafe"
                    ),
                    transactions=(ExtractedTransaction(
                        TransactionDirection.DEBIT, 750, "USD", merchant="Cafe"
                    ),),
                    raw_response={}, structured_output={},
                    model_id="test", document_kind="statement",
                    statement=ExtractedStatement(
                        issuer="Qik", account_reference="card-evt"
                    ),
                )

        workflow.ingest_and_extract(run=run, message=message, extractor=_Extractor())
        from wallet_v2.persistence.models import StatementReviewBatch
        batch = session.scalars(select(StatementReviewBatch)).one()
        line = batch.statement.lines[0]
        workflow.resolve_statement_line(run=run, line=line, outcome=ReconciliationOutcome.NEW)
        workflow.approve_statement_batch(run=run, batch=batch, reviewer_id="operator")
        session.commit()
        event = session.scalars(select(FinancialEvent)).one()
        # The enrichment query plan requires a bounded event date; the workflow
        # may leave transaction_date unset, so pin one inside the record window.
        event.transaction_date = date(2026, 1, 10)
        session.commit()
        return event.id


class TestCandidateResearch:
    def test_get_research(self, client: TestClient) -> None:
        candidate_id, _ = _ingest_notification(client, merchant="Shop", amount=1234, account_reference="card-cand")
        with client.app.state.session_factory() as session:
            session.add(AdvisoryResearch(
                candidate_id=candidate_id,
                evidence_grade="no_recommendation",
                query_inputs={"rationale": "no history"},
                evidence_ids={"records": [{"record_id": "r1", "grade": "context_only", "counter_party": "X"}]},
                integrity_hash="deadbeef",
            ))
            session.commit()

        response = client.get(f"/enrichment/candidates/{candidate_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["candidate_id"] == str(candidate_id)
        assert data["is_finalizable"] is False
        assert data["recommendation"] is False
        assert data["evidence_grade"] == "no_recommendation"
        assert data["evidence"][0]["record_id"] == "r1"

    def test_get_research_missing(self, client: TestClient) -> None:
        response = client.get("/enrichment/candidates/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_list_by_account_disabled_preview(self, client: TestClient) -> None:
        candidate_id, account_id = _ingest_notification(
            client, merchant="Shop", amount=1234, account_reference="card-acct"
        )
        with client.app.state.session_factory() as session:
            session.add(AdvisoryResearch(
                candidate_id=candidate_id,
                evidence_grade="merchant_history",
                query_inputs={"remote_account_id": "acct-9"},
                evidence_ids={"records": []},
                integrity_hash="abc",
            ))
            session.commit()

        response = client.get(f"/enrichment/candidates/account/{account_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["is_finalizable"] is False
        # Even a merchant_history grade never surfaces as a recommendation:
        # candidate research is advisory context only, never finalizable.
        assert data[0]["evidence_grade"] == "merchant_history"
        assert data[0]["recommendation"] is False


class TestEventGenerate:
    def test_generate_requires_mcp(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        client.app.state.mcp_client = None
        response = client.post(f"/enrichment/events/{event_id}/generate")
        assert response.status_code == 503

    def test_generate_no_mapping_is_no_recommendation(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        client.app.state.mcp_client = FakeReadOnlyMcp()
        response = client.post(f"/enrichment/events/{event_id}/generate")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 1
        assert data["evidence_grade"] == "no_recommendation"
        assert data["can_finalize"] is False

    def test_generate_with_exact_match(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        # Seed accounts catalog + mapping so the query plan resolves.
        with client.app.state.session_factory() as session:
            _seed_catalog(session, "accounts", [{"id": "acct-remote", "name": "X", "archived": False}])
            _seed_catalog(session, "categories", [{"id": "cat-1", "name": "Food", "archived": False}])
            _seed_catalog(session, "labels", [{"id": "lbl-1", "name": "L", "archived": False}])
            snap = session.scalars(select(CatalogSyncSnapshot).where(
                CatalogSyncSnapshot.resource_kind == "accounts"
            )).one()
            AccountMappingService(session).create_mapping(
                financial_account_id=_event_account_id(session, event_id),
                remote_account_id="acct-remote",
                snapshot_id=snap.id,
            )
            session.commit()
        fake = FakeReadOnlyMcp(records=[
            McpRecord(
                id="rec-1", account_id="acct-remote", amount_value=-7.5,
                currency="USD", record_date="2026-01-10",
                counter_party="CAFE", category=McpCategory(id="cat-1", name="Food"),
                labels=(McpLabel(id="lbl-1", name="L"),), payment_type="debit_card",
            )
        ])
        client.app.state.mcp_client = fake
        response = client.post(f"/enrichment/events/{event_id}/generate")
        assert response.status_code == 200
        data = response.json()
        assert data["evidence_grade"] == "exact_recurrence"
        assert data["selected_account_id"] == "acct-remote"
        assert data["can_finalize"] is True


def _event_account_id(session, event_id: str) -> object:
    event = session.get(FinancialEvent, event_id)
    return event.account_id


class TestEventOverride:
    def test_override_creates_new_version(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        with client.app.state.session_factory() as session:
            _seed_catalog(session, "accounts", [{"id": "acct-1", "name": "A", "archived": False}])
            _seed_catalog(session, "categories", [{"id": "cat-1", "name": "C", "archived": False}])
            _seed_catalog(session, "labels", [{"id": "lbl-1", "name": "L", "archived": False}])
            session.commit()

        client.app.state.mcp_client = None
        body = {
            "account_id": "acct-1", "category_id": "cat-1",
            "label_ids": ["lbl-1"], "payment_type": "debit_card",
        }
        r1 = client.post(f"/enrichment/events/{event_id}/override", json=body)
        assert r1.status_code == 200
        assert r1.json()["version"] == 1
        assert r1.json()["evidence_grade"] == "operator_override"
        assert r1.json()["can_finalize"] is True

        # Second override creates version 2; version 1 remains immutable.
        r2 = client.post(f"/enrichment/events/{event_id}/override", json=body)
        assert r2.status_code == 200
        assert r2.json()["version"] == 2

        with client.app.state.session_factory() as session:
            decisions = session.scalars(
                select(EnrichmentDecision)
                .where(EnrichmentDecision.financial_event_id == event_id)
                .order_by(EnrichmentDecision.version)
            ).all()
            assert len(decisions) == 2
            assert decisions[0].version == 1 and decisions[0].finalized is False
            assert decisions[1].version == 2

    def test_override_invalid_catalog_fails_closed(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        with client.app.state.session_factory() as session:
            _seed_catalog(session, "accounts", [{"id": "acct-1", "name": "A", "archived": False}])
            _seed_catalog(session, "categories", [{"id": "cat-1", "name": "C", "archived": False}])
            _seed_catalog(session, "labels", [{"id": "lbl-1", "name": "L", "archived": False}])
            session.commit()

        client.app.state.mcp_client = None
        body = {
            "account_id": "acct-missing", "category_id": None,
            "label_ids": [], "payment_type": None,
        }
        response = client.post(f"/enrichment/events/{event_id}/override", json=body)
        assert response.status_code == 422

    def test_override_archived_account_fails_closed(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        with client.app.state.session_factory() as session:
            _seed_catalog(session, "accounts", [{"id": "acct-arch", "name": "A", "archived": True}])
            session.commit()
        client.app.state.mcp_client = None
        body = {
            "account_id": "acct-arch", "category_id": None,
            "label_ids": [], "payment_type": None,
        }
        response = client.post(f"/enrichment/events/{event_id}/override", json=body)
        assert response.status_code == 422


class TestEventFinalizeAndPreview:
    def _override(self, client: TestClient, event_id: str) -> None:
        with client.app.state.session_factory() as session:
            _seed_catalog(session, "accounts", [{"id": "acct-1", "name": "A", "archived": False}])
            _seed_catalog(session, "categories", [{"id": "cat-1", "name": "C", "archived": False}])
            _seed_catalog(session, "labels", [{"id": "lbl-1", "name": "L", "archived": False}])
            session.commit()
        client.app.state.mcp_client = None
        body = {
            "account_id": "acct-1", "category_id": "cat-1",
            "label_ids": ["lbl-1"], "payment_type": "debit_card",
        }
        r = client.post(f"/enrichment/events/{event_id}/override", json=body)
        assert r.status_code == 200

    def test_finalize_then_dry_run_preview_no_write(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        self._override(client, event_id)

        # Finalize.
        fr = client.post(f"/enrichment/events/{event_id}/finalize")
        assert fr.status_code == 200
        assert fr.json()["finalized"] is True

        # Dry-run preview returns the exact payload and never writes.
        pr = client.get(f"/enrichment/events/{event_id}/dry-run-preview")
        assert pr.status_code == 200
        payload = pr.json()
        assert payload["submitted"] is False
        assert payload["payload"]["accountId"] == "acct-1"
        assert payload["payload"]["categoryId"] == "cat-1"
        assert payload["payload"]["labelIds"] == ["lbl-1"]
        assert payload["payload"]["paymentType"] == "debit_card"
        # amount_minor 750 -> 7.5 major units
        assert payload["payload"]["amount"]["value"] == 7.5
        assert payload["payload"]["amount"]["currencyCode"] == "USD"

        # No Wallet write: no import command row is created by the preview.
        from wallet_v2.persistence.models import ImportCommand
        with client.app.state.session_factory() as session:
            assert session.scalars(select(ImportCommand)).first() is None

    def test_finalize_newer_version_supersedes_prior(self, client: TestClient) -> None:
        """Finalizing v2 after v1 is finalized yields only v2 finalized, no 500.

        The partial unique index allows only one finalized decision per event;
        finalizing a newer version must atomically unfinalize the prior one
        rather than raising an integrity error.
        """
        event_id = _setup_event(client)
        self._override(client, event_id)  # version 1

        fr1 = client.post(f"/enrichment/events/{event_id}/finalize")
        assert fr1.status_code == 200
        assert fr1.json()["version"] == 1
        assert fr1.json()["finalized"] is True

        body = {
            "account_id": "acct-1", "category_id": "cat-1",
            "label_ids": ["lbl-1"], "payment_type": "debit_card",
        }
        r2 = client.post(f"/enrichment/events/{event_id}/override", json=body)
        assert r2.status_code == 200
        assert r2.json()["version"] == 2

        fr2 = client.post(f"/enrichment/events/{event_id}/finalize")
        assert fr2.status_code == 200  # not a 500
        assert fr2.json()["version"] == 2
        assert fr2.json()["finalized"] is True

        with client.app.state.session_factory() as session:
            decisions = session.scalars(
                select(EnrichmentDecision)
                .where(EnrichmentDecision.financial_event_id == event_id)
                .order_by(EnrichmentDecision.version)
            ).all()
            finalized_versions = [d.version for d in decisions if d.finalized]
            assert finalized_versions == [2]
            assert decisions[0].version == 1 and decisions[0].finalized is False

    def test_generate_version_conflict_returns_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A duplicate (event, version) insert maps to a clean 409, not a 500."""
        import wallet_v2.api.routes.enrichment as enrichment_routes

        event_id = _setup_event(client)
        client.app.state.mcp_client = FakeReadOnlyMcp()
        monkeypatch.setattr(
            enrichment_routes, "_next_version", lambda session, event_id: 1
        )

        r1 = client.post(f"/enrichment/events/{event_id}/generate")
        assert r1.status_code == 200
        assert r1.json()["version"] == 1

        r2 = client.post(f"/enrichment/events/{event_id}/generate")
        assert r2.status_code == 409

    def test_finalize_non_recommendation_fails_closed(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        client.app.state.mcp_client = FakeReadOnlyMcp()  # no mapping -> no_recommendation
        client.post(f"/enrichment/events/{event_id}/generate")
        response = client.post(f"/enrichment/events/{event_id}/finalize")
        assert response.status_code == 409

    def test_dry_run_preview_not_finalized_fails_closed(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        self._override(client, event_id)
        response = client.get(f"/enrichment/events/{event_id}/dry-run-preview")
        assert response.status_code == 409

    def test_get_event_enrichment_404_when_absent(self, client: TestClient) -> None:
        event_id = _setup_event(client)
        response = client.get(f"/enrichment/events/{event_id}")
        assert response.status_code == 404


class TestPreEnrichmentProposals:
    def test_generate_batch_proposals_and_line_enrichment(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup")
            from wallet_v2.application.contracts import ExtractedStatement, ExtractedTransaction, ExtractionResult, MailboxMessage
            from wallet_v2.domain.enums import ReconciliationOutcome

            msg = MailboxMessage(
                provider="imap", account_fingerprint="a" * 64, folder="INBOX",
                uid_validity=7, message_uid=801, sender="s@t.local", recipient="w@t.local",
                subject="Stmt", message_id_header="<s801@t.local>", received_at=_now(), body_text="text",
            )
            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(TransactionDirection.DEBIT, 1200, "USD", merchant="Coffee Shop"),
                        transactions=(ExtractedTransaction(TransactionDirection.DEBIT, 1200, "USD", merchant="Coffee Shop"),),
                        raw_response={}, structured_output={}, model_id="test", document_kind="statement",
                        statement=ExtractedStatement(issuer="Bank", account_reference="card-pre"),
                    )
            workflow.ingest_and_extract(run=run, message=msg, extractor=_Extractor())
            from wallet_v2.persistence.models import StatementReviewBatch
            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            line.transaction_date = date(2026, 1, 10)
            workflow.resolve_statement_line(run=run, line=line, outcome=ReconciliationOutcome.NEW)
            batch_id = str(batch.id)
            line_id = str(line.id)

            _seed_catalog(session, "accounts", [{"id": "acct-remote", "name": "R", "archived": False}])
            _seed_catalog(session, "categories", [{"id": "cat-coffee", "name": "Coffee", "archived": False}])
            _seed_catalog(session, "labels", [{"id": "lbl-1", "name": "L", "archived": False}])
            snap = session.scalars(select(CatalogSyncSnapshot).where(CatalogSyncSnapshot.resource_kind == "accounts")).one()
            AccountMappingService(session).create_mapping(
                financial_account_id=batch.statement.account_id,
                remote_account_id="acct-remote",
                snapshot_id=snap.id,
            )
            session.commit()

        fake = FakeReadOnlyMcp(records=[
            McpRecord(
                id="rec-coffee", account_id="acct-remote", amount_value=-12.0,
                currency="USD", record_date="2026-01-10", counter_party="Coffee Shop",
                category=McpCategory(id="cat-coffee", name="Coffee"),
                labels=(McpLabel(id="lbl-1", name="L"),), payment_type="debit_card",
            )
        ])
        client.app.state.mcp_client = fake

        # Generate batch proposals pre-approval
        res = client.post(f"/enrichment/batches/{batch_id}/generate-proposals")
        assert res.status_code == 200
        proposals = res.json()
        assert len(proposals) == 1
        assert proposals[0]["line_id"] == line_id
        assert proposals[0]["event_id"] is None
        assert proposals[0]["evidence_grade"] == "exact_recurrence"
        assert proposals[0]["selected_category_id"] == "cat-coffee"

        # Read line enrichment
        lres = client.get(f"/enrichment/lines/{line_id}")
        assert lres.status_code == 200
        assert lres.json()["line_id"] == line_id
        assert lres.json()["selected_category_id"] == "cat-coffee"

    def test_line_override_pre_approval(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup")
            from wallet_v2.application.contracts import ExtractedStatement, ExtractedTransaction, ExtractionResult, MailboxMessage
            from wallet_v2.domain.enums import ReconciliationOutcome

            msg = MailboxMessage(
                provider="imap", account_fingerprint="a" * 64, folder="INBOX",
                uid_validity=7, message_uid=802, sender="s@t.local", recipient="w@t.local",
                subject="Stmt", message_id_header="<s802@t.local>", received_at=_now(), body_text="text",
            )
            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(TransactionDirection.DEBIT, 500, "USD", merchant="Bookstore"),
                        transactions=(ExtractedTransaction(TransactionDirection.DEBIT, 500, "USD", merchant="Bookstore"),),
                        raw_response={}, structured_output={}, model_id="test", document_kind="statement",
                        statement=ExtractedStatement(issuer="Bank", account_reference="card-pre2"),
                    )
            workflow.ingest_and_extract(run=run, message=msg, extractor=_Extractor())
            from wallet_v2.persistence.models import StatementReviewBatch
            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            workflow.resolve_statement_line(run=run, line=line, outcome=ReconciliationOutcome.NEW)
            line_id = str(line.id)
            _seed_catalog(session, "accounts", [{"id": "acct-w", "name": "W", "archived": False}])
            _seed_catalog(session, "categories", [{"id": "cat-books", "name": "Books", "archived": False}])
            session.commit()

        body = {
            "account_id": "acct-w",
            "category_id": "cat-books",
            "label_ids": [],
            "payment_type": "debit_card",
        }
        res = client.post(f"/enrichment/lines/{line_id}/override", json=body)
        assert res.status_code == 200
        data = res.json()
        assert data["line_id"] == line_id
        assert data["evidence_grade"] == "operator_override"
        assert data["selected_category_id"] == "cat-books"
        assert data["can_finalize"] is True


class TestAtomicApproveAndFinalize:
    def test_approve_batch_atomically_finalizes_enrichment(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup")
            from wallet_v2.application.contracts import ExtractedStatement, ExtractedTransaction, ExtractionResult, MailboxMessage
            from wallet_v2.domain.enums import ReconciliationOutcome

            msg = MailboxMessage(
                provider="imap", account_fingerprint="a" * 64, folder="INBOX",
                uid_validity=7, message_uid=803, sender="s@t.local", recipient="w@t.local",
                subject="Stmt", message_id_header="<s803@t.local>", received_at=_now(), body_text="text",
            )
            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(TransactionDirection.DEBIT, 1500, "USD", merchant="Tech Store"),
                        transactions=(ExtractedTransaction(TransactionDirection.DEBIT, 1500, "USD", merchant="Tech Store"),),
                        raw_response={}, structured_output={}, model_id="test", document_kind="statement",
                        statement=ExtractedStatement(issuer="Bank", account_reference="card-atomic"),
                    )
            workflow.ingest_and_extract(run=run, message=msg, extractor=_Extractor())
            from wallet_v2.persistence.models import StatementReviewBatch
            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            workflow.resolve_statement_line(run=run, line=line, outcome=ReconciliationOutcome.NEW)
            batch_id = str(batch.id)
            line_id = str(line.id)

            _seed_catalog(session, "accounts", [{"id": "acct-main", "name": "M", "archived": False}])
            _seed_catalog(session, "categories", [{"id": "cat-gadgets", "name": "Gadgets", "archived": False}])
            session.commit()

        # Call approve-batch with enrichment overrides
        approve_body = {
            "reviewer_id": "operator-1",
            "enrichment_overrides": {
                line_id: {
                    "account_id": "acct-main",
                    "category_id": "cat-gadgets",
                    "label_ids": [],
                    "payment_type": "debit_card",
                }
            }
        }
        res = client.post(f"/commands/approve-batch/{batch_id}", json=approve_body)
        assert res.status_code == 200
        data = res.json()
        assert data["event_count"] == 1
        event_id = data["events"][0]["event_id"]

        # Verify event enrichment is finalized
        eres = client.get(f"/enrichment/events/{event_id}")
        assert eres.status_code == 200
        edata = eres.json()
        assert edata["finalized"] is True
        assert edata["selected_category_id"] == "cat-gadgets"

    def test_approve_batch_rollback_on_finalization_failure(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup")
            from wallet_v2.application.contracts import ExtractedStatement, ExtractedTransaction, ExtractionResult, MailboxMessage
            from wallet_v2.domain.enums import ReconciliationOutcome

            msg = MailboxMessage(
                provider="imap", account_fingerprint="a" * 64, folder="INBOX",
                uid_validity=7, message_uid=804, sender="s@t.local", recipient="w@t.local",
                subject="Stmt", message_id_header="<s804@t.local>", received_at=_now(), body_text="text",
            )
            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(TransactionDirection.DEBIT, 2000, "USD", merchant="Unknown Store"),
                        transactions=(ExtractedTransaction(TransactionDirection.DEBIT, 2000, "USD", merchant="Unknown Store"),),
                        raw_response={}, structured_output={}, model_id="test", document_kind="statement",
                        statement=ExtractedStatement(issuer="Bank", account_reference="card-fail"),
                    )
            workflow.ingest_and_extract(run=run, message=msg, extractor=_Extractor())
            from wallet_v2.persistence.models import StatementReviewBatch
            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            workflow.resolve_statement_line(run=run, line=line, outcome=ReconciliationOutcome.NEW)
            batch_id = str(batch.id)
            line_id = str(line.id)

            _seed_catalog(session, "accounts", [{"id": "acct-main", "name": "M", "archived": False}])
            snap = session.scalars(select(CatalogSyncSnapshot).where(CatalogSyncSnapshot.resource_kind == "accounts")).one()
            AccountMappingService(session).create_mapping(
                financial_account_id=batch.statement.account_id,
                remote_account_id="acct-main",
                snapshot_id=snap.id,
            )
            session.commit()

        # Fake MCP returns no match -> no_recommendation grade
        fake = FakeReadOnlyMcp(records=[])
        client.app.state.mcp_client = fake

        # Generate proposal (which will be no_recommendation)
        pres = client.post(f"/enrichment/batches/{batch_id}/generate-proposals")
        assert pres.status_code == 200
        assert pres.json()[0]["evidence_grade"] == "no_recommendation"

        # Attempt to approve batch without providing an override -> finalization fails on no_recommendation
        res = client.post(f"/commands/approve-batch/{batch_id}", json={"reviewer_id": "op"})
        assert res.status_code == 422

        # Verify atomic rollback: batch is still open, no events committed
        with factory() as session:
            from uuid import UUID
            from wallet_v2.persistence.models import StatementReviewBatch, FinancialEvent
            b = session.get(StatementReviewBatch, UUID(batch_id))
            assert b.state == "open"
            events = session.scalars(select(FinancialEvent)).all()
            assert len(events) == 0

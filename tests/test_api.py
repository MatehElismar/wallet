"""Hermetic integration tests for the FastAPI reconciliation API."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from wallet_v2.api.app import create_test_app
from wallet_v2.application import WalletWorkflow
from wallet_v2.domain.enums import (
    AuditEventKind,
    IntegrationMode,
    ReconciliationOutcome,
    TransactionDirection,
)
from wallet_v2.persistence.base import Base
from wallet_v2.persistence.models import (
    AuditEvent,
    ExecutionRun,
    StatementReviewBatch,
)


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


class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestListBatches:
    def test_empty(self, client: TestClient) -> None:
        response = client.get("/batches")
        assert response.status_code == 200
        assert response.json() == {"batches": []}

    def test_with_open_batch(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=101,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-101@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 5000, "USD", merchant="Coffee Shop"
                        ),
                        transactions=(
                            ExtractedTransaction(
                                TransactionDirection.DEBIT, 5000, "USD", merchant="Coffee Shop"
                            ),
                            ExtractedTransaction(
                                TransactionDirection.CREDIT, 20000, "USD", merchant="Refund"
                            ),
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(
                            issuer="Qik", account_reference="card-1234",
                            statement_date=datetime(2026, 1, 10).date(),
                            currency="USD",
                            period_start=datetime(2026, 1, 1).date(),
                            period_end=datetime(2026, 1, 10).date(),
                            opening_balance_minor=100000,
                            closing_balance_minor=85000,
                        ),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

        response = client.get("/batches")
        assert response.status_code == 200
        data = response.json()
        assert len(data["batches"]) == 1
        batch = data["batches"][0]
        assert batch["line_count"] == 2
        assert batch["line_resolved_count"] >= 0
        assert batch["state"] == "open"
        assert batch["account_issuer"] == "Qik"
        assert batch["account_reference"] == "card-1234"
        assert batch["statement_currency"] == "USD"


class TestBatchDetail:
    def test_not_found(self, client: TestClient) -> None:
        response = client.get("/batches/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_detail_with_lines(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-detail")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=102,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-102@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 1234, "DOP", merchant="Test Shop"
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(
                            issuer="Qik", account_reference="card-5678",
                            statement_date=datetime(2026, 1, 11).date(),
                        ),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            batch_id = str(batch.id)

        response = client.get(f"/batches/{batch_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["batch_id"] == batch_id
        assert data["state"] == "open"
        assert data["account"]["issuer"] == "Qik"
        assert data["account"]["external_reference"] == "card-5678"
        assert len(data["lines"]) == 1
        line = data["lines"][0]
        assert line["line_index"] == 1
        assert line["amount_minor"] == 1234
        assert line["currency"] == "DOP"
        assert line["direction"] == "debit"


class TestResolveLine:
    def test_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/commands/resolve-line/00000000-0000-0000-0000-000000000000",
            json={"outcome": "new"},
        )
        assert response.status_code == 404

    def test_resolve_new(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-resolve")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=103,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-103@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 999, "USD", merchant="Ambiguous Shop"
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-x"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            line_id = str(line.id)

        response = client.post(
            f"/commands/resolve-line/{line_id}",
            json={"outcome": "new", "note": "Unrecognized merchant"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["outcome"] == "new"
        assert data["method"] == "manual"
        assert data["note"] == "Unrecognized merchant"

    def test_resolve_matched_with_observation(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(
                mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-matched"
            )
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )

            class _NotificationExtractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT,
                            1500,
                            "USD",
                            merchant="Matched Store",
                            issuer="Qik",
                            account_reference="card-matched",
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                    )

            notif_extractor = _NotificationExtractor()
            workflow.ingest_and_extract(
                run=run,
                message=MailboxMessage(
                    provider="imap",
                    account_fingerprint="a" * 64,
                    folder="INBOX",
                    uid_validity=7,
                    message_uid=400,
                    sender="alerts@test.local",
                    recipient="wallet@test.local",
                    subject="Notification",
                    message_id_header="<notif-400@test.local>",
                    received_at=_now(),
                    body_text="Notification.",
                ),
                extractor=notif_extractor,
            )

            class _StatementExtractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT,
                            1500,
                            "USD",
                            merchant="Matched Store",
                        ),
                        transactions=(
                            ExtractedTransaction(
                                TransactionDirection.DEBIT,
                                1500,
                                "USD",
                                merchant="Matched Store",
                            ),
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(
                            issuer="Qik", account_reference="card-matched"
                        ),
                    )

            workflow.ingest_and_extract(
                run=run,
                message=MailboxMessage(
                    provider="imap",
                    account_fingerprint="a" * 64,
                    folder="INBOX",
                    uid_validity=7,
                    message_uid=401,
                    sender="alerts@test.local",
                    recipient="wallet@test.local",
                    subject="Statement",
                    message_id_header="<stmt-401@test.local>",
                    received_at=_now(),
                    body_text="Statement.",
                ),
                extractor=_StatementExtractor(),
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            line_id = str(line.id)

            from wallet_v2.persistence.models import TransactionObservation
            observations = session.scalars(
                select(TransactionObservation)
            ).all()
            assert len(observations) > 0
            obs_id = str(observations[0].id)

        response = client.post(
            f"/commands/resolve-line/{line_id}",
            json={"outcome": "matched", "observation_id": obs_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["outcome"] == "matched"
        assert data["method"] == "manual"

    def test_resolve_matched_missing_observation_rejected(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(
                mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-matched-reject"
            )
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=402,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-402@test.local>",
                received_at=_now(),
                body_text="Statement.",
            )

            tx = ExtractedTransaction(
                TransactionDirection.DEBIT, 2000, "USD", merchant="Shop"
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=tx,
                        transactions=(tx,),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-mr"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]

        response = client.post(
            f"/commands/resolve-line/{line.id}",
            json={"outcome": "matched"},
        )
        assert response.status_code == 422
        assert "observation" in response.json()["detail"].lower()

    def test_resolve_ambiguous(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(
                mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-ambiguous"
            )
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=403,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-403@test.local>",
                received_at=_now(),
                body_text="Statement.",
            )

            tx = ExtractedTransaction(
                TransactionDirection.DEBIT, 3000, "USD", merchant="Amb"
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=tx,
                        transactions=(tx,),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-amb"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]

        response = client.post(
            f"/commands/resolve-line/{line.id}",
            json={"outcome": "ambiguous", "note": "Need more info"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["outcome"] == "ambiguous"
        assert data["method"] == "manual"
        assert data["note"] == "Need more info"

    def test_invalid_outcome(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-invalid")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=104,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-104@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 100, "USD", merchant="Shop"
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-y"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]

        response = client.post(
            f"/commands/resolve-line/{line.id}",
            json={"outcome": "bogus"},
        )
        assert response.status_code == 422


class TestMapAccount:
    def test_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/commands/map-account/00000000-0000-0000-0000-000000000000",
            json={"wallet_account_reference": "w-1"},
        )
        assert response.status_code == 404

    def test_map_success(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-map")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=105,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-105@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 100, "USD", merchant="Shop"
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-z"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            account_id = str(batch.statement.account.id)

        response = client.post(
            f"/commands/map-account/{account_id}",
            json={"wallet_account_reference": "wallet-card-42"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == account_id
        assert data["wallet_account_reference"] == "wallet-card-42"

    def test_blank_reference_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/commands/map-account/00000000-0000-0000-0000-000000000000",
            json={"wallet_account_reference": ""},
        )
        assert response.status_code == 422


class TestApproveBatch:
    def test_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/commands/approve-batch/00000000-0000-0000-0000-000000000000",
            json={"reviewer_id": "test-user"},
        )
        assert response.status_code == 404

    def test_ambiguous_blocks_approval(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-ambig-approve")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            notification = ExtractedTransaction(
                TransactionDirection.DEBIT, 1000, "DOP", merchant="One",
                reference="DUPE", issuer="Qik", account_reference="card-a",
            )
            result = ExtractionResult(
                is_transaction=True, transaction=notification,
                raw_response={}, structured_output={"is_transaction": True},
                model_id="test",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return result

            extractor = _Extractor()
            for uid in (201, 202):
                workflow.ingest_and_extract(
                    run=run,
                    message=MailboxMessage(
                        provider="imap", account_fingerprint="a" * 64,
                        folder="INBOX", uid_validity=7, message_uid=uid,
                        sender="alerts@test.local", recipient="wallet@test.local",
                        subject="Notification", message_id_header=f"<notif-{uid}@test.local>",
                        received_at=_now(), body_text="Notification.",
                    ),
                    extractor=extractor,
                )
            stmt_result = ExtractionResult(
                is_transaction=True, transaction=notification,
                raw_response={}, structured_output={"is_transaction": True},
                model_id="test", document_kind="statement",
                statement=ExtractedStatement(issuer="Qik", account_reference="card-a"),
            )

            class _StmtExtractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return stmt_result

            workflow.ingest_and_extract(
                run=run,
                message=MailboxMessage(
                    provider="imap", account_fingerprint="a" * 64,
                    folder="INBOX", uid_validity=7, message_uid=203,
                    sender="alerts@test.local", recipient="wallet@test.local",
                    subject="Statement", message_id_header="<stmt-203@test.local>",
                    received_at=_now(), body_text="Statement.",
                ),
                extractor=_StmtExtractor(),
            )
            session.commit()
            batch = session.scalars(select(StatementReviewBatch)).one()
            batch_id = str(batch.id)

        response = client.post(
            f"/commands/approve-batch/{batch_id}",
            json={"reviewer_id": "test-user"},
        )
        assert response.status_code == 422
        assert "ambiguous" in response.json()["detail"].lower()

    def test_approve_success(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-approve")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=106,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-106@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 1000, "USD", merchant="Shop A"
                        ),
                        transactions=(ExtractedTransaction(
                            TransactionDirection.DEBIT, 1000, "USD", merchant="Shop A"
                        ),),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-approve"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            workflow.resolve_statement_line(
                run=run, line=line,
                outcome=ReconciliationOutcome.NEW,
            )
            workflow.map_financial_account(
                run=run, account=batch.statement.account,
                wallet_account_reference="wallet-ref-1",
            )
            session.commit()
            batch_id = str(batch.id)

        response = client.post(
            f"/commands/approve-batch/{batch_id}",
            json={"reviewer_id": "operator", "note": "All good"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_count"] == 1
        assert len(data["events"]) == 1
        assert data["events"][0]["currency"] == "USD"
        assert data["events"][0]["amount_minor"] == 1000


class TestDryRunImport:
    def test_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/commands/dry-run-import/00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code == 404

    def test_dry_run_success(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-dryrun")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=107,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-107@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 750, "USD", merchant="Cafe"
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-dry"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            workflow.resolve_statement_line(
                run=run, line=line,
                outcome=ReconciliationOutcome.NEW,
            )
            workflow.map_financial_account(
                run=run, account=batch.statement.account,
                wallet_account_reference="wallet-dry-1",
            )
            events = workflow.approve_statement_batch(
                run=run, batch=batch, reviewer_id="operator",
            )
            session.commit()
            event_id = str(events[0].id)

        response = client.post(f"/commands/dry-run-import/{event_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["event_id"] == event_id
        assert "command_id" in data
        assert data["status"] == "queued"


class TestBatchDetailEligibleObservations:
    def test_eligible_observations_included(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(
                mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-eligible"
            )
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )

            class _NotificationExtractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT,
                            5000,
                            "USD",
                            merchant="Eligible Co",
                            issuer="Qik",
                            account_reference="card-eligible",
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                    )

            notif_extractor = _NotificationExtractor()
            workflow.ingest_and_extract(
                run=run,
                message=MailboxMessage(
                    provider="imap",
                    account_fingerprint="a" * 64,
                    folder="INBOX",
                    uid_validity=7,
                    message_uid=500,
                    sender="alerts@test.local",
                    recipient="wallet@test.local",
                    subject="Notification",
                    message_id_header="<notif-500@test.local>",
                    received_at=_now(),
                    body_text="Notification.",
                ),
                extractor=notif_extractor,
            )

            class _StatementExtractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    tx = ExtractedTransaction(
                        TransactionDirection.DEBIT, 5000, "USD", merchant="Eligible Co"
                    )
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=tx,
                        transactions=(tx,),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(
                            issuer="Qik", account_reference="card-eligible"
                        ),
                    )

            workflow.ingest_and_extract(
                run=run,
                message=MailboxMessage(
                    provider="imap",
                    account_fingerprint="a" * 64,
                    folder="INBOX",
                    uid_validity=7,
                    message_uid=501,
                    sender="alerts@test.local",
                    recipient="wallet@test.local",
                    subject="Statement",
                    message_id_header="<stmt-501@test.local>",
                    received_at=_now(),
                    body_text="Statement.",
                ),
                extractor=_StatementExtractor(),
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            batch_id = str(batch.id)

        response = client.get(f"/batches/{batch_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["lines"]) == 1
        line = data["lines"][0]
        assert "eligible_observations" in line
        assert len(line["eligible_observations"]) == 1
        obs = line["eligible_observations"][0]
        assert obs["source_merchant"] == "Eligible Co"
        assert obs["amount_minor"] == 5000
        assert obs["currency"] == "USD"
        assert obs["direction"] == "debit"


class TestProxyHeaderSafety:
    def test_health_does_not_require_auth(self, client: TestClient) -> None:
        response = client.get("/health", headers={})
        assert response.status_code == 200

    def test_batches_called_without_authorization_ok(self, client: TestClient) -> None:
        response = client.get("/batches", headers={})
        assert response.status_code == 200

    def test_command_routes_no_auth_required(self, client: TestClient) -> None:
        response = client.post(
            "/commands/approve-batch/00000000-0000-0000-0000-000000000000",
            json={"reviewer_id": "anon"},
            headers={},
        )
        assert response.status_code == 404


class TestNoProductionSqlite:
    def test_create_app_without_settings_fails_closed(self) -> None:
        from wallet_v2.api.app import create_app
        from wallet_v2.config import ConfigError

        with pytest.raises(ConfigError):
            create_app()

    def test_create_app_with_valid_settings_succeeds(self) -> None:
        from wallet_v2.api.app import create_app
        from wallet_v2.config import Settings, DatabaseSettings, load_settings

        settings = load_settings({
            "WALLET_V2__ENVIRONMENT": "dev",
            "WALLET_V2__DATABASE__URL": "postgresql+psycopg://user:pass@localhost:5432/wallet_v2",
        })
        app = create_app(settings)
        try:
            assert "postgresql" in str(app.state.engine.url)
        finally:
            app.state.engine.dispose()

    def test_create_test_app_still_uses_sqlite(self) -> None:
        from wallet_v2.api.app import create_test_app

        app = create_test_app()
        try:
            assert "sqlite" in str(app.state.engine.url)
        finally:
            app.state.engine.dispose()


class TestCommandRunCompletion:
    def test_resolve_line_finishes_run(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-finish")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=200,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-200@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 500, "USD", merchant="Test"
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-fin"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            line_id = str(line.id)

        response = client.post(
            f"/commands/resolve-line/{line_id}",
            json={"outcome": "new"},
        )
        assert response.status_code == 200

        from wallet_v2.persistence.models import ExecutionRun
        with factory() as session:
            runs = session.scalars(
                select(ExecutionRun)
                .where(ExecutionRun.label == "operator-console")
                .order_by(ExecutionRun.started_at.desc())
            ).all()
            assert len(runs) > 0
            latest = runs[0]
            assert latest.outcome == "succeeded"
            assert latest.finished_at is not None

    def test_workflow_error_persists_failed_run(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(
                mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-wf-error"
            )
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            tx = ExtractedTransaction(
                TransactionDirection.DEBIT, 1000, "USD", merchant="AmbiguousShop",
                issuer="Qik", account_reference="card-ambig",
                reference="DUPE-AMB",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True, transaction=tx,
                        raw_response={}, structured_output={},
                        model_id="test",
                    )

            extractor = _Extractor()
            for uid in (601, 602):
                workflow.ingest_and_extract(
                    run=run,
                    message=MailboxMessage(
                        provider="imap", account_fingerprint="a" * 64,
                        folder="INBOX", uid_validity=7, message_uid=uid,
                        sender="alerts@test.local", recipient="wallet@test.local",
                        subject="Notification", message_id_header=f"<notif-{uid}@test.local>",
                        received_at=_now(), body_text="Notification.",
                    ),
                    extractor=extractor,
                )

            stmt_result = ExtractionResult(
                is_transaction=True, transaction=tx,
                transactions=(tx,),
                raw_response={}, structured_output={},
                model_id="test", document_kind="statement",
                statement=ExtractedStatement(
                    issuer="Qik", account_reference="card-ambig",
                ),
            )

            class _StmtExtractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return stmt_result

            workflow.ingest_and_extract(
                run=run,
                message=MailboxMessage(
                    provider="imap", account_fingerprint="a" * 64,
                    folder="INBOX", uid_validity=7, message_uid=603,
                    sender="alerts@test.local", recipient="wallet@test.local",
                    subject="Statement", message_id_header="<stmt-603@test.local>",
                    received_at=_now(), body_text="Statement.",
                ),
                extractor=_StmtExtractor(),
            )
            session.commit()
            batch = session.scalars(select(StatementReviewBatch)).one()
            batch_id = str(batch.id)

        response = client.post(
            f"/commands/approve-batch/{batch_id}",
            json={"reviewer_id": "test-user"},
        )
        assert response.status_code == 422
        assert "ambiguous" in response.json()["detail"].lower()

        with factory() as session:
            runs = session.scalars(
                select(ExecutionRun)
                .where(ExecutionRun.label == "operator-console")
                .where(ExecutionRun.outcome == "failed")
                .order_by(ExecutionRun.started_at.desc())
            ).all()
            assert len(runs) == 1
            failed_run = runs[0]
            assert failed_run.finished_at is not None
            assert failed_run.error_summary is not None
            assert "ambiguous" in failed_run.error_summary.lower()

            audit = session.scalars(
                select(AuditEvent)
                .where(AuditEvent.execution_run_id == failed_run.id)
                .where(AuditEvent.event_kind == AuditEventKind.EXECUTION_RUN_FINISHED)
            ).first()
            assert audit is not None
            assert audit.payload == {"outcome": "failed"}

            saved_batch = session.get(StatementReviewBatch, batch.id)
            assert saved_batch is not None
            assert saved_batch.state == "open"

    def test_map_account_finishes_run(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-map-finish")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=201,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-201@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 300, "USD", merchant="Map"
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-map-fin"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            session.commit()

            batch = session.scalars(select(StatementReviewBatch)).one()
            account_id = str(batch.statement.account.id)

        response = client.post(
            f"/commands/map-account/{account_id}",
            json={"wallet_account_reference": "w-fin-1"},
        )
        assert response.status_code == 200

        from wallet_v2.persistence.models import ExecutionRun
        with factory() as session:
            runs = session.scalars(
                select(ExecutionRun)
                .where(ExecutionRun.label == "operator-console")
                .order_by(ExecutionRun.started_at.desc())
            ).all()
            assert len(runs) > 0
            latest = runs[0]
            assert latest.outcome == "succeeded"
            assert latest.finished_at is not None


class TestDryRunEventId:
    def test_dry_run_import_uses_event_id_not_line_id(self, client: TestClient) -> None:
        factory = client.app.state.session_factory
        with factory() as session:
            workflow = WalletWorkflow(session, now=_now)
            run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="setup-evtid")
            from wallet_v2.application.contracts import (
                ExtractedStatement,
                ExtractedTransaction,
                ExtractionResult,
                MailboxMessage,
            )
            message = MailboxMessage(
                provider="imap",
                account_fingerprint="a" * 64,
                folder="INBOX",
                uid_validity=7,
                message_uid=300,
                sender="alerts@test.local",
                recipient="wallet@test.local",
                subject="Statement",
                message_id_header="<stmt-300@test.local>",
                received_at=_now(),
                body_text="Statement text.",
            )

            class _Extractor:
                def extract(self, _msg: object) -> ExtractionResult:
                    return ExtractionResult(
                        is_transaction=True,
                        transaction=ExtractedTransaction(
                            TransactionDirection.DEBIT, 100, "USD", merchant="EvtId"
                        ),
                        raw_response={},
                        structured_output={},
                        model_id="test",
                        document_kind="statement",
                        statement=ExtractedStatement(issuer="Qik", account_reference="card-evtid"),
                    )

            workflow.ingest_and_extract(
                run=run, message=message, extractor=_Extractor()
            )
            batch = session.scalars(select(StatementReviewBatch)).one()
            line = batch.statement.lines[0]
            workflow.resolve_statement_line(
                run=run, line=line,
                outcome=ReconciliationOutcome.NEW,
            )
            workflow.map_financial_account(
                run=run, account=batch.statement.account,
                wallet_account_reference="w-evtid-1",
            )
            events = workflow.approve_statement_batch(
                run=run, batch=batch, reviewer_id="operator",
            )
            session.commit()
            event_id = str(events[0].id)
            assert event_id != str(line.id), "event ID must differ from line ID"

        response = client.post(f"/commands/dry-run-import/{event_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["event_id"] == event_id

    def test_dry_run_import_nonexistent_event_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/commands/dry-run-import/00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code == 404

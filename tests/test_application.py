"""Hermetic end-to-end tests for controlled workflow execution."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from wallet_v2.application import (
    AccountMappingService,
    ExtractedStatement,
    ExtractedTransaction,
    ExtractionResult,
    MailboxMessage,
    WalletWorkflow,
)
from wallet_v2.application.service import WorkflowError
from wallet_v2.domain.enums import (
    CandidateStatus,
    DocumentKind,
    FinancialEventStatus,
    IntegrationMode,
    ReviewDecision,
    ReconciliationOutcome,
    TransactionDirection,
)
from wallet_v2.persistence.models import (
    AuditEvent,
    BankStatement,
    CatalogSyncCursor,
    CatalogSyncSnapshot,
    FinancialEvent,
    Inbox,
    InboxCursorHistory,
    MessageContentMetadata,
    ProcessingAttempt,
    StatementReviewBatch,
    TransactionObservation,
    WalletAttempt,
)


class _Extractor:
    def __init__(self, result: ExtractionResult) -> None:
        self.result = result
        self.calls = 0

    def extract(self, message: MailboxMessage) -> ExtractionResult:
        self.calls += 1
        return self.result


def _message(message_uid: int = 42) -> MailboxMessage:
    return MailboxMessage(
        provider="imap",
        account_fingerprint="a" * 64,
        folder="INBOX",
        uid_validity=7,
        message_uid=message_uid,
        sender="alerts@example.test",
        recipient="wallet@example.test",
        subject="Synthetic purchase",
        message_id_header="<synthetic-42@example.test>",
        received_at=datetime.now(timezone.utc),
        body_text="Synthetic transaction notice.",
    )


def _transaction_result(amount: int = 1234) -> ExtractionResult:
    return ExtractionResult(
        is_transaction=True,
        transaction=ExtractedTransaction(
            direction=TransactionDirection.DEBIT,
            amount_minor=amount,
            currency="USD",
            merchant="Synthetic Merchant",
        ),
        raw_response={"synthetic": True},
        structured_output={"is_transaction": True, "amount_minor": amount},
        model_id="test-extractor",
    )


class TestControlledWorkflow:
    def test_notification_candidates_are_provisional_and_not_importable(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(
            mode=IntegrationMode.DRY_RUN,
            trigger="test",
            label="test-controlled-run",
            metadata={"mailbox": "dry_run", "api_key": "<redacted>"},
        )
        source, candidates, tasks = workflow.ingest_and_extract(
            run=run, message=_message(), extractor=_Extractor(_transaction_result())
        )
        assert len(candidates) == len(tasks) == 1
        candidate, task = candidates[0], tasks[0]
        assert source.execution_run_id == run.id
        assert candidate.status == CandidateStatus.UNDER_REVIEW

        workflow.decide_review(
            run=run,
            task=task,
            reviewer_id="operator@example.test",
            decision=ReviewDecision.APPROVED,
        )
        with pytest.raises(WorkflowError, match="provisional"):
            workflow.import_approved_candidate(
                run=run, candidate=candidate, wallet=None
            )
        session.flush()

        observation = session.scalar(
            select(TransactionObservation).where(
                TransactionObservation.candidate_id == candidate.id
            )
        )
        assert observation is not None
        assert observation.status == "provisional"
        assert session.scalars(select(WalletAttempt)).all() == []

    def test_duplicate_delivery_is_idempotent_and_reprocess_is_append_only(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="replay")
        extractor = _Extractor(_transaction_result())
        message = _message()
        source, first_candidates, _ = workflow.ingest_and_extract(run=run, message=message, extractor=extractor)
        duplicate_source, duplicate_candidate, duplicate_task = workflow.ingest_and_extract(
            run=run, message=message, extractor=extractor
        )
        _, second_candidates, _ = workflow.reprocess(run=run, message=message, extractor=extractor)
        session.flush()

        assert len(first_candidates) == len(second_candidates) == 1
        first, second = first_candidates[0], second_candidates[0]
        assert duplicate_source.id == source.id
        assert duplicate_candidate == () and duplicate_task == ()
        assert extractor.calls == 2
        assert first.candidate_version == 1
        assert second.candidate_version == 2
        attempts = session.scalars(
            select(ProcessingAttempt)
            .where(ProcessingAttempt.source_message_id == source.id)
            .order_by(ProcessingAttempt.attempt_index)
        ).all()
        assert [attempt.attempt_index for attempt in attempts] == [1, 2]

    def test_statement_reconciles_notification_and_creates_importable_events_as_a_batch(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="statement")
        notification = ExtractedTransaction(
            TransactionDirection.DEBIT,
            1000,
            "DOP",
            merchant="One",
            reference="BANK-REF-1",
            issuer="Qik",
            account_reference="card-1234",
        )
        _, notification_candidates, _ = workflow.ingest_and_extract(
            run=run,
            message=_message(41),
            extractor=_Extractor(
                ExtractionResult(
                    is_transaction=True,
                    transaction=notification,
                    raw_response={},
                    structured_output={"is_transaction": True},
                    model_id="test-extractor",
                )
            ),
        )
        assert len(notification_candidates) == 1
        first = ExtractedTransaction(
            TransactionDirection.DEBIT,
            1000,
            "DOP",
            merchant="One",
            reference="BANK-REF-1",
            transaction_date=None,
            posting_date=None,
        )
        second = ExtractedTransaction(
            TransactionDirection.CREDIT, 200, "DOP", merchant="Two"
        )
        result = ExtractionResult(
            is_transaction=True,
            transaction=first,
            transactions=(first, second),
            raw_response={},
            structured_output={"is_transaction": True, "transactions": [{}, {}]},
            model_id="test-extractor",
            document_kind=DocumentKind.STATEMENT,
            statement=ExtractedStatement(
                issuer="Qik",
                account_reference="card-1234",
            ),
        )

        _, candidates, tasks = workflow.ingest_and_extract(
            run=run, message=_message(42), extractor=_Extractor(result)
        )

        assert candidates == () and tasks == ()
        statement = session.scalar(select(BankStatement))
        assert statement is not None
        assert len(statement.lines) == 2
        assert statement.lines[0].resolution is not None
        assert statement.lines[0].resolution.outcome == ReconciliationOutcome.MATCHED
        batch = session.scalar(select(StatementReviewBatch))
        assert batch is not None

        events = workflow.approve_statement_batch(
            run=run,
            batch=batch,
            reviewer_id="operator@example.test",
        )
        assert len(events) == 2
        assert notification_candidates[0].status == CandidateStatus.DROPPED
        assert notification_candidates[0].review_task is not None
        assert notification_candidates[0].review_task.state == "superseded"
        assert statement.status == "approved"
        assert statement.account.wallet_account_reference is None
        with pytest.raises(WorkflowError, match="mapp"):
            workflow.import_approved_financial_event(
                run=run, event=events[0], wallet=None
            )
        snap = CatalogSyncSnapshot(
            resource_kind="accounts",
            snapshot_version=1,
            catalog_data={
                "version": 1,
                "resource_kind": "accounts",
                "snapshot_version": 1,
                "item_count": 1,
                "items": [
                    {"id": "wallet-card-1", "name": "Card", "archived": False}
                ],
            },
        )
        session.add(snap)
        session.flush()
        session.add(
            CatalogSyncCursor(
                resource_kind="accounts",
                current_snapshot=snap,
                last_synced_at=datetime.now(timezone.utc),
            )
        )
        session.flush()
        mapping_svc = AccountMappingService(session)
        mapping_svc.create_mapping(
            financial_account_id=statement.account.id,
            remote_account_id="wallet-card-1",
            snapshot_id=snap.id,
        )
        session.flush()
        command = workflow.import_approved_financial_event(
            run=run, event=events[0], wallet=None
        )
        session.flush()
        assert command.financial_event_id == events[0].id
        assert session.scalars(select(FinancialEvent)).all() == list(events)
        assert session.scalars(select(WalletAttempt)).all() == []

    def test_ambiguous_statement_match_requires_manual_resolution_before_batch_approval(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="ambiguous")
        notification = ExtractedTransaction(
            TransactionDirection.DEBIT,
            1000,
            "DOP",
            merchant="One",
            reference="DUPLICATE-REF",
            issuer="Qik",
            account_reference="card-1234",
        )
        result = ExtractionResult(
            is_transaction=True,
            transaction=notification,
            raw_response={},
            structured_output={"is_transaction": True},
            model_id="test-extractor",
        )
        for uid in (51, 52):
            workflow.ingest_and_extract(
                run=run, message=_message(uid), extractor=_Extractor(result)
            )
        statement_result = ExtractionResult(
            is_transaction=True,
            transaction=notification,
            raw_response={},
            structured_output={"is_transaction": True},
            model_id="test-extractor",
            document_kind=DocumentKind.STATEMENT,
            statement=ExtractedStatement(issuer="Qik", account_reference="card-1234"),
        )
        workflow.ingest_and_extract(
            run=run, message=_message(53), extractor=_Extractor(statement_result)
        )
        batch = session.scalar(select(StatementReviewBatch))
        assert batch is not None
        line = batch.statement.lines[0]
        assert line.resolution is not None
        assert line.resolution.outcome == ReconciliationOutcome.AMBIGUOUS
        with pytest.raises(WorkflowError, match="ambiguous"):
            workflow.approve_statement_batch(
                run=run, batch=batch, reviewer_id="operator@example.test"
            )

        observation = session.scalars(select(TransactionObservation)).first()
        assert observation is not None
        workflow.resolve_statement_line(
            run=run,
            line=line,
            outcome=ReconciliationOutcome.MATCHED,
            observation=observation,
            note="Selected against duplicate alert",
        )
        events = workflow.approve_statement_batch(
            run=run, batch=batch, reviewer_id="operator@example.test"
        )
        assert len(events) == 1
        assert observation.status == "confirmed"

    def test_duplicate_statement_under_another_uid_does_not_create_duplicate_events(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="duplicate-statement")
        line = ExtractedTransaction(
            TransactionDirection.DEBIT,
            1234,
            "DOP",
            merchant="One",
            reference="BANK-REF-1",
        )
        result = ExtractionResult(
            is_transaction=True,
            transaction=line,
            raw_response={},
            structured_output={"is_transaction": True},
            model_id="test-extractor",
            document_kind=DocumentKind.STATEMENT,
            statement=ExtractedStatement(issuer="Qik", account_reference="card-1234"),
        )
        workflow.ingest_and_extract(
            run=run, message=_message(61), extractor=_Extractor(result)
        )
        batch = session.scalar(select(StatementReviewBatch))
        assert batch is not None
        events = workflow.approve_statement_batch(
            run=run, batch=batch, reviewer_id="operator@example.test"
        )
        assert len(events) == 1
        workflow.ingest_and_extract(
            run=run, message=_message(62), extractor=_Extractor(result)
        )
        session.flush()
        assert len(session.scalars(select(BankStatement)).all()) == 1
        assert len(session.scalars(select(FinancialEvent)).all()) == 1

    def test_changed_statement_reprocess_supersedes_prior_open_batch(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="statement-reprocess")
        statement = ExtractedStatement(issuer="Qik", account_reference="card-1234")
        initial_line = ExtractedTransaction(TransactionDirection.DEBIT, 100, "DOP", merchant="One")
        initial = ExtractionResult(
            is_transaction=True,
            transaction=initial_line,
            raw_response={},
            structured_output={"is_transaction": True},
            model_id="test-extractor",
            document_kind=DocumentKind.STATEMENT,
            statement=statement,
        )
        message = _message(63)
        workflow.ingest_and_extract(run=run, message=message, extractor=_Extractor(initial))
        prior = session.scalar(select(BankStatement))
        assert prior is not None and prior.review_batch is not None
        revised_line = ExtractedTransaction(TransactionDirection.DEBIT, 100, "DOP", merchant="Revised")
        revised = ExtractionResult(
            is_transaction=True,
            transaction=revised_line,
            raw_response={},
            structured_output={"is_transaction": True},
            model_id="test-extractor",
            document_kind=DocumentKind.STATEMENT,
            statement=statement,
        )
        workflow.reprocess(run=run, message=message, extractor=_Extractor(revised))
        session.flush()
        assert prior.status == "superseded"
        assert prior.review_batch.state == "superseded"
        active = session.scalars(
            select(BankStatement).where(BankStatement.status == "open")
        ).all()
        assert len(active) == 1

    def test_reversal_statement_line_links_the_prior_canonical_event(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="reversal")
        statement = ExtractedStatement(issuer="Qik", account_reference="card-1234")
        posted = ExtractionResult(
            is_transaction=True,
            transaction=ExtractedTransaction(
                TransactionDirection.DEBIT, 1000, "DOP", reference="PURCHASE-1"
            ),
            raw_response={},
            structured_output={"is_transaction": True},
            model_id="test-extractor",
            document_kind=DocumentKind.STATEMENT,
            statement=statement,
        )
        workflow.ingest_and_extract(run=run, message=_message(64), extractor=_Extractor(posted))
        first_batch = session.scalar(select(StatementReviewBatch))
        assert first_batch is not None
        original_event = workflow.approve_statement_batch(
            run=run, batch=first_batch, reviewer_id="operator@example.test"
        )[0]
        reversed_entry = ExtractionResult(
            is_transaction=True,
            transaction=ExtractedTransaction(
                TransactionDirection.CREDIT,
                1000,
                "DOP",
                reference="REVERSAL-1",
                event_status=FinancialEventStatus.REVERSED,
                related_reference="PURCHASE-1",
            ),
            raw_response={},
            structured_output={"is_transaction": True},
            model_id="test-extractor",
            document_kind=DocumentKind.STATEMENT,
            statement=statement,
        )
        workflow.ingest_and_extract(run=run, message=_message(65), extractor=_Extractor(reversed_entry))
        second_batch = session.scalars(
            select(StatementReviewBatch).where(StatementReviewBatch.id != first_batch.id)
        ).one()
        reversal_event = workflow.approve_statement_batch(
            run=run, batch=second_batch, reviewer_id="operator@example.test"
        )[0]
        assert reversal_event.status == FinancialEventStatus.REVERSED
        assert reversal_event.reverses_event_id == original_event.id

    def test_invalid_amount_fails_before_candidate_or_review(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="invalid")
        with pytest.raises(WorkflowError, match="strictly positive"):
            workflow.ingest_and_extract(
                run=run, message=_message(), extractor=_Extractor(_transaction_result(0))
            )

    def test_processed_message_records_headers_and_committed_cursor(self, session: Session) -> None:
        workflow = WalletWorkflow(session)
        run = workflow.start_run(mode=IntegrationMode.DRY_RUN, trigger="test", label="trace")
        message = _message()
        source, _, _ = workflow.ingest_and_extract(
            run=run, message=message, extractor=_Extractor(_transaction_result())
        )
        workflow.finish_run(run, outcome="succeeded")
        session.flush()

        inbox = session.get(Inbox, source.inbox_id)
        assert inbox is not None
        assert (inbox.uid_validity, inbox.last_seen_uid) == (7, 42)
        history = session.scalars(select(InboxCursorHistory)).all()
        assert [(entry.uid_validity, entry.last_seen_uid) for entry in history] == [(7, 42)]
        metadata = session.scalar(
            select(MessageContentMetadata).where(
                MessageContentMetadata.source_message_id == source.id
            )
        )
        assert metadata is not None
        assert metadata.subject == "Synthetic purchase"
        event_kinds = {event.event_kind for event in session.scalars(select(AuditEvent)).all()}
        assert "execution_run_started" in event_kinds
        assert "execution_run_finished" in event_kinds

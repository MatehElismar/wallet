"""Historical reconciliation-run persistence invariants."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from wallet_v2.application import WalletWorkflow
from wallet_v2.application.contracts import (
    ExtractedStatement,
    ExtractedTransaction,
    ExtractionResult,
    MailboxMessage,
)
from wallet_v2.application.reconciliation_runs import materialize_reconciliation_run
from wallet_v2.domain.enums import (
    IntegrationMode,
    StatementStatus,
    TransactionDirection,
)
from wallet_v2.persistence.models import BankStatement, ReconciliationRun


def test_reconciliation_run_requires_an_inclusive_date_range(session) -> None:
    session.add(
        ReconciliationRun(
            period_start=date(2026, 2, 1),
            period_end=date(2026, 1, 31),
            state="materialized",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_materialize_empty_range_creates_a_durable_zero_coverage_snapshot(session) -> None:
    run = materialize_reconciliation_run(
        session,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    session.commit()

    assert run.state == "materialized"
    assert run.statement_account_count == 0
    assert run.included_statement_line_count == 0
    assert run.undated_excluded_line_count == 0
    assert run.account_coverages == []


def test_materialized_snapshot_rejects_any_later_update(session) -> None:
    run = materialize_reconciliation_run(
        session,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    session.commit()

    run.period_end = date(2026, 2, 1)
    with pytest.raises(ValueError, match="immutable"):
        session.flush()


def test_materialized_snapshot_rejects_bulk_update_bypasses(session) -> None:
    run = materialize_reconciliation_run(
        session,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    session.commit()

    with pytest.raises(IntegrityError, match="immutable"):
        session.execute(
            update(ReconciliationRun)
            .where(ReconciliationRun.id == run.id)
            .values(period_end=date(2026, 2, 1))
        )


def test_materialize_covers_all_discovered_statement_accounts_without_account_input(
    session,
) -> None:
    now = lambda: datetime(2026, 2, 15, tzinfo=timezone.utc)
    workflow = WalletWorkflow(session, now=now)
    execution_run = workflow.start_run(
        mode=IntegrationMode.DRY_RUN, trigger="test", label="statement-evidence"
    )
    transactions = (
        ExtractedTransaction(
            TransactionDirection.DEBIT,
            1500,
            "USD",
            merchant="In range",
            posting_date=date(2026, 1, 15),
        ),
        ExtractedTransaction(
            TransactionDirection.CREDIT,
            300,
            "USD",
            merchant="No posted date",
        ),
    )

    class Extractor:
        def extract(self, _message: object) -> ExtractionResult:
            return ExtractionResult(
                is_transaction=True,
                transaction=transactions[0],
                transactions=transactions,
                raw_response={},
                structured_output={},
                model_id="test",
                document_kind="statement",
                statement=ExtractedStatement(
                    issuer="Example Bank",
                    account_reference="acct-1234",
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 1, 31),
                    currency="USD",
                ),
            )

    workflow.ingest_and_extract(
        run=execution_run,
        message=MailboxMessage(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            uid_validity=1,
            message_uid=1,
            sender="statements@example.test",
            recipient="operator@example.test",
            subject="January statement",
            message_id_header="<statement-1@example.test>",
            received_at=now(),
            body_text="statement",
        ),
        extractor=Extractor(),
    )

    run = materialize_reconciliation_run(
        session,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    session.commit()

    assert run.statement_account_count == 1
    assert run.included_statement_line_count == 1
    assert run.undated_excluded_line_count == 1
    assert len(run.account_coverages) == 1
    coverage = run.account_coverages[0]
    assert coverage.issuer_snapshot == "Example Bank"
    assert coverage.included_line_count == 1
    assert coverage.undated_excluded_line_count == 1
    assert coverage.new_count == 1
    assert coverage.unresolved_line_count == 0

    statement = session.scalar(select(BankStatement))
    assert statement is not None
    statement.status = StatementStatus.SUPERSEDED
    replacement_run = materialize_reconciliation_run(
        session,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    session.commit()

    assert replacement_run.statement_account_count == 0
    assert replacement_run.included_statement_line_count == 0

    coverage.new_count = 0
    coverage.unresolved_line_count = 1
    with pytest.raises(ValueError, match="immutable"):
        session.flush()

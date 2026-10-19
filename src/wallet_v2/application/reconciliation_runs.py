"""Materialize durable, statement-evidence-only historical run snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from wallet_v2.domain.enums import StatementStatus
from wallet_v2.persistence.models import (
    BankStatement,
    BankStatementLine,
    FinancialAccount,
    ReconciliationRun,
    ReconciliationRunAccountCoverage,
)


@dataclass(slots=True)
class _CoverageAccumulator:
    account: FinancialAccount
    statement_ids: set[UUID] = field(default_factory=set)
    included: int = 0
    undated: int = 0
    unresolved: int = 0
    new: int = 0
    matched: int = 0
    ambiguous: int = 0
    ignored: int = 0


def materialize_reconciliation_run(
    session: Session,
    *,
    period_start: date,
    period_end: date,
) -> ReconciliationRun:
    """Persist one immutable snapshot of available *statement* evidence.

    Effective date is ``posting_date`` where available, otherwise
    ``transaction_date``. Lines without either date are not covered; they are
    reported separately only when their statement period overlaps the selected
    range. Superseded and rejected statement versions are excluded entirely.
    No integration or financial-mutation path is invoked.
    """

    if period_start > period_end:
        raise ValueError("period_start must be on or before period_end")

    statements = session.scalars(
        select(BankStatement)
        .where(BankStatement.status.in_((StatementStatus.OPEN, StatementStatus.APPROVED)))
        .options(
            selectinload(BankStatement.account),
            selectinload(BankStatement.lines).selectinload(
                BankStatementLine.resolution
            ),
        )
    ).all()
    coverages: dict[UUID, _CoverageAccumulator] = {}

    for statement in statements:
        account = statement.account
        statement_overlaps = (
            statement.period_start is not None
            and statement.period_end is not None
            and statement.period_start <= period_end
            and statement.period_end >= period_start
        )
        included_lines = []
        undated_lines = []
        for line in statement.lines:
            effective_date = line.posting_date or line.transaction_date
            if effective_date is not None and period_start <= effective_date <= period_end:
                included_lines.append(line)
            elif effective_date is None and statement_overlaps:
                undated_lines.append(line)
        if not included_lines and not undated_lines:
            continue

        coverage = coverages.setdefault(account.id, _CoverageAccumulator(account))
        coverage.statement_ids.add(statement.id)
        coverage.undated += len(undated_lines)
        for line in included_lines:
            coverage.included += 1
            resolution = line.resolution
            if resolution is None:
                coverage.unresolved += 1
                continue
            outcome = getattr(resolution.outcome, "value", resolution.outcome)
            if outcome not in {"new", "matched", "ambiguous", "ignored"}:
                raise ValueError(f"unsupported statement-evidence outcome: {outcome!r}")
            setattr(coverage, outcome, getattr(coverage, outcome) + 1)

    coverage_rows = [
        ReconciliationRunAccountCoverage(
            financial_account_id=coverage.account.id,
            issuer_snapshot=coverage.account.issuer,
            external_reference_snapshot=coverage.account.external_reference,
            statement_count=len(coverage.statement_ids),
            included_line_count=coverage.included,
            undated_excluded_line_count=coverage.undated,
            unresolved_line_count=coverage.unresolved,
            new_count=coverage.new,
            matched_count=coverage.matched,
            ambiguous_count=coverage.ambiguous,
            ignored_count=coverage.ignored,
        )
        for coverage in coverages.values()
    ]
    run = ReconciliationRun(
        period_start=period_start,
        period_end=period_end,
        state="materialized",
        statement_account_count=len(coverages),
        included_statement_line_count=sum(
            coverage.included for coverage in coverages.values()
        ),
        undated_excluded_line_count=sum(
            coverage.undated for coverage in coverages.values()
        ),
        account_coverages=coverage_rows,
    )
    session.add(run)
    session.flush()
    return run

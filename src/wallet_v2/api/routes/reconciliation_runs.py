"""Read-only historical statement-evidence reconciliation-run endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from wallet_v2.api.deps import get_session
from wallet_v2.api.schemas import (
    ReconciliationRunAccountCoverageView,
    ReconciliationRunDetail,
    ReconciliationRunSummary,
    ReconciliationRunSummaryList,
)
from wallet_v2.persistence.models import ReconciliationRun


router = APIRouter(prefix="/reconciliation-runs", tags=["reconciliation-runs"])


def _summary(run: ReconciliationRun) -> ReconciliationRunSummary:
    return ReconciliationRunSummary(
        run_id=run.id,
        period_start=run.period_start,
        period_end=run.period_end,
        state=run.state,
        statement_account_count=run.statement_account_count,
        included_statement_line_count=run.included_statement_line_count,
        undated_excluded_line_count=run.undated_excluded_line_count,
        created_at=run.created_at,
    )


@router.get("", response_model=ReconciliationRunSummaryList)
def list_reconciliation_runs(
    session: Session = Depends(get_session),
) -> ReconciliationRunSummaryList:
    runs = session.scalars(
        select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc())
    ).all()
    return ReconciliationRunSummaryList(runs=[_summary(run) for run in runs])


@router.get("/{run_id}", response_model=ReconciliationRunDetail)
def get_reconciliation_run(
    run_id: UUID,
    session: Session = Depends(get_session),
) -> ReconciliationRunDetail:
    run = session.scalar(
        select(ReconciliationRun)
        .where(ReconciliationRun.id == run_id)
        .options(selectinload(ReconciliationRun.account_coverages))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="reconciliation run not found")
    return ReconciliationRunDetail(
        **_summary(run).model_dump(),
        account_coverages=[
            ReconciliationRunAccountCoverageView(
                financial_account_id=coverage.financial_account_id,
                issuer=coverage.issuer_snapshot,
                external_reference=coverage.external_reference_snapshot,
                statement_count=coverage.statement_count,
                included_line_count=coverage.included_line_count,
                undated_excluded_line_count=coverage.undated_excluded_line_count,
                unresolved_line_count=coverage.unresolved_line_count,
                new_count=coverage.new_count,
                matched_count=coverage.matched_count,
                ambiguous_count=coverage.ambiguous_count,
                ignored_count=coverage.ignored_count,
            )
            for coverage in run.account_coverages
        ],
    )

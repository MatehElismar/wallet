"""Statement batch read endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from wallet_v2.api.deps import get_session
from wallet_v2.api.schemas import (
    BatchDetail,
    BatchSummary,
    BatchSummaryList,
    FinancialAccountView,
    ObservationView,
    ReconciliationLinkView,
    StatementLineView,
)
from wallet_v2.persistence.models import (
    BankStatementLine,
    ReconciliationLink,
    StatementReviewBatch,
    TransactionObservation,
)
from wallet_v2.domain.enums import ObservationStatus

router = APIRouter(prefix="/batches", tags=["batches"])


def _e_val(field: object) -> str:
    return field.value if hasattr(field, "value") else str(field)


def _eligible_observations(
    account_id: UUID, line: BankStatementLine, session: Session
) -> list[TransactionObservation]:
    linked_observation_ids = session.scalars(
        select(ReconciliationLink.observation_id).where(
            ReconciliationLink.observation_id.isnot(None)
        )
    ).all()
    excluded_ids = set(linked_observation_ids)
    return session.scalars(
        select(TransactionObservation).where(
            and_(
                TransactionObservation.account_id == account_id,
                TransactionObservation.status == ObservationStatus.PROVISIONAL,
                TransactionObservation.amount_minor == line.amount_minor,
                TransactionObservation.currency == line.currency,
                TransactionObservation.direction == line.direction,
                ~TransactionObservation.id.in_(excluded_ids) if excluded_ids else True,
            )
        )
    ).all()


def _build_summary(batch: StatementReviewBatch) -> BatchSummary:
    statement = batch.statement
    lines = statement.lines
    line_count = len(lines)
    resolved_count = 0
    ambiguous_count = 0
    for line in lines:
        if line.resolution is not None:
            resolved_count += 1
            if line.resolution.outcome == "ambiguous":
                ambiguous_count += 1
    return BatchSummary(
        batch_id=batch.id,
        statement_id=statement.id,
        account_issuer=statement.account.issuer,
        account_reference=statement.account.external_reference,
        statement_currency=statement.currency,
        statement_date=statement.statement_date,
        period_start=statement.period_start,
        period_end=statement.period_end,
        line_count=line_count,
        line_resolved_count=resolved_count,
        ambiguous_count=ambiguous_count,
        state=batch.state,
        created_at=batch.created_at,
    )


def _build_line_view(line: BankStatementLine, session: Session) -> StatementLineView:
    resolution: ReconciliationLinkView | None = None
    observation: ObservationView | None = None
    link: ReconciliationLink | None = line.resolution
    if link is not None:
        resolution = ReconciliationLinkView(
            outcome=_e_val(link.outcome),
            method=_e_val(link.method),
            confidence=link.confidence,
            note=link.note,
        )
        if link.observation is not None:
            obs = link.observation
            observation = ObservationView(
                observation_id=obs.id,
                source_merchant=obs.merchant,
                source_reference=obs.reference,
                status=_e_val(obs.status),
                amount_minor=obs.amount_minor,
                currency=obs.currency,
                direction=_e_val(obs.direction),
                transaction_date=obs.transaction_date,
            )
    eligible = _eligible_observations(line.statement.account_id, line, session)
    eligible_views = [
        ObservationView(
            observation_id=obs.id,
            source_merchant=obs.merchant,
            source_reference=obs.reference,
            status=_e_val(obs.status),
            amount_minor=obs.amount_minor,
            currency=obs.currency,
            direction=_e_val(obs.direction),
            transaction_date=obs.transaction_date,
        )
        for obs in eligible
    ]
    return StatementLineView(
        line_id=line.id,
        line_index=line.line_index,
        direction=_e_val(line.direction),
        amount_minor=line.amount_minor,
        currency=line.currency,
        merchant=line.merchant,
        external_reference=line.external_reference,
        description=line.description,
        transaction_date=line.transaction_date,
        posting_date=line.posting_date,
        running_balance_minor=line.running_balance_minor,
        event_status=_e_val(line.event_status),
        event_id=line.event.id if line.event is not None else None,
        reconciliation=resolution,
        observation=observation,
        eligible_observations=eligible_views,
    )


@router.get("", response_model=BatchSummaryList)
def list_open_batches(
    session: Session = Depends(get_session),
) -> BatchSummaryList:
    batches = session.scalars(
        select(StatementReviewBatch).where(
            StatementReviewBatch.state == "open"
        ).order_by(StatementReviewBatch.created_at.desc())
    ).all()
    return BatchSummaryList(batches=[_build_summary(b) for b in batches])


@router.get("/{batch_id}", response_model=BatchDetail)
def get_batch_detail(
    batch_id: UUID,
    session: Session = Depends(get_session),
) -> BatchDetail:
    batch = session.get(StatementReviewBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    statement = batch.statement
    account_view: FinancialAccountView | None = None
    if statement.account is not None:
        acct = statement.account
        account_view = FinancialAccountView(
            account_id=acct.id,
            issuer=acct.issuer,
            external_reference=acct.external_reference,
            wallet_account_reference=acct.wallet_account_reference,
        )
    return BatchDetail(
        batch_id=batch.id,
        statement_id=statement.id,
        state=batch.state,
        statement_status=_e_val(statement.status),
        statement_currency=statement.currency,
        statement_date=statement.statement_date,
        period_start=statement.period_start,
        period_end=statement.period_end,
        opening_balance_minor=statement.opening_balance_minor,
        closing_balance_minor=statement.closing_balance_minor,
        account=account_view,
        lines=[_build_line_view(line, session) for line in statement.lines],
        reviewer_id=batch.reviewer_id,
        decided_at=batch.decided_at,
        decision_note=batch.decision_note,
        created_at=batch.created_at,
    )

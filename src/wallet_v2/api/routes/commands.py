"""Command endpoints: resolve lines, map accounts, approve batches, dry-run import."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from wallet_v2.api.deps import get_session
from wallet_v2.api.schemas import (
    ApproveBatchRequest,
    ApproveBatchResponse,
    DryRunImportResponse,
    FinancialEventView,
    MapAccountRequest,
    MapAccountResponse,
    ResolveLineRequest,
    ResolveLineResponse,
)
from wallet_v2.application.service import WorkflowError, WalletWorkflow
from wallet_v2.domain.enums import IntegrationMode, ReconciliationOutcome
from wallet_v2.persistence.models import (
    BankStatementLine,
    ExecutionRun,
    FinancialAccount,
    FinancialEvent,
    StatementReviewBatch,
    TransactionObservation,
)

router = APIRouter(prefix="/commands", tags=["commands"])


def _start_command_run(session: Session) -> tuple[WalletWorkflow, ExecutionRun]:
    workflow = WalletWorkflow(session)
    run = workflow.start_run(
        mode=IntegrationMode.DRY_RUN,
        trigger="manual",
        label="operator-console",
        initiator="unauthenticated",
    )
    return workflow, run


def _finish_command_run(wf: WalletWorkflow, run: ExecutionRun, outcome: str, error: str | None = None) -> None:
    wf.finish_run(run, outcome=outcome, error=error)


def _enum_val(field: object) -> str:
    return field.value if hasattr(field, "value") else str(field)


def _event_to_view(event: FinancialEvent) -> FinancialEventView:
    return FinancialEventView(
        event_id=event.id,
        direction=_enum_val(event.direction),
        amount_minor=event.amount_minor,
        currency=event.currency,
        merchant=event.merchant,
        reference=event.reference,
        transaction_date=event.transaction_date,
        posting_date=event.posting_date,
        event_status=_enum_val(event.status),
    )


@router.post("/resolve-line/{line_id}", response_model=ResolveLineResponse)
def resolve_line(
    line_id: UUID,
    body: ResolveLineRequest,
    session: Session = Depends(get_session),
) -> ResolveLineResponse:
    line = session.get(BankStatementLine, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="statement line not found")
    try:
        outcome = ReconciliationOutcome(body.outcome)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"invalid outcome: {body.outcome!r}; must be new, matched, ambiguous, or ignored",
        )
    observation = None
    if body.observation_id is not None:
        observation = session.get(TransactionObservation, body.observation_id)
        if observation is None:
            raise HTTPException(status_code=422, detail="observation not found")
    wf, run = _start_command_run(session)
    sp = session.begin_nested()
    try:
        link = wf.resolve_statement_line(
            run=run,
            line=line,
            outcome=outcome,
            observation=observation,
            note=body.note,
        )
    except WorkflowError as exc:
        sp.rollback()
        _finish_command_run(wf, run, "failed", str(exc))
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc))
    _finish_command_run(wf, run, "succeeded")
    return ResolveLineResponse(
        link_id=link.id,
        outcome=_enum_val(link.outcome),
        method=_enum_val(link.method),
        note=link.note,
    )


@router.post("/map-account/{account_id}", response_model=MapAccountResponse)
def map_account(
    account_id: UUID,
    body: MapAccountRequest,
    session: Session = Depends(get_session),
) -> MapAccountResponse:
    account = session.get(FinancialAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="financial account not found")
    wf, run = _start_command_run(session)
    sp = session.begin_nested()
    try:
        account = wf.map_financial_account(
            run=run,
            account=account,
            wallet_account_reference=body.wallet_account_reference,
        )
    except WorkflowError as exc:
        sp.rollback()
        _finish_command_run(wf, run, "failed", str(exc))
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc))
    _finish_command_run(wf, run, "succeeded")
    return MapAccountResponse(
        account_id=account.id,
        wallet_account_reference=account.wallet_account_reference or "",
    )


@router.post("/approve-batch/{batch_id}", response_model=ApproveBatchResponse)
def approve_batch(
    batch_id: UUID,
    body: ApproveBatchRequest,
    session: Session = Depends(get_session),
) -> ApproveBatchResponse:
    batch = session.get(StatementReviewBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    wf, run = _start_command_run(session)
    sp = session.begin_nested()
    try:
        events = wf.approve_statement_batch(
            run=run,
            batch=batch,
            reviewer_id=body.reviewer_id,
            note=body.note,
        )
    except WorkflowError as exc:
        sp.rollback()
        _finish_command_run(wf, run, "failed", str(exc))
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc))
    _finish_command_run(wf, run, "succeeded")
    return ApproveBatchResponse(
        batch_id=batch.id,
        event_count=len(events),
        events=[_event_to_view(e) for e in events],
    )


@router.post("/dry-run-import/{event_id}", response_model=DryRunImportResponse)
def dry_run_import(
    event_id: UUID,
    session: Session = Depends(get_session),
) -> DryRunImportResponse:
    event = session.get(FinancialEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="financial event not found")
    wf, run = _start_command_run(session)
    sp = session.begin_nested()
    try:
        command = wf.import_approved_financial_event(
            run=run,
            event=event,
            wallet=None,
        )
    except WorkflowError as exc:
        sp.rollback()
        _finish_command_run(wf, run, "failed", str(exc))
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc))
    _finish_command_run(wf, run, "succeeded")
    return DryRunImportResponse(
        command_id=command.id,
        event_id=command.financial_event_id,
        status=_enum_val(command.status),
        issued_at=command.issued_at,
    )

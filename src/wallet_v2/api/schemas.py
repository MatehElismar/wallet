"""Pydantic request/response schemas for the reconciliation API."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    ok: bool = True


class BatchSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: UUID
    statement_id: UUID
    account_issuer: str | None = None
    account_reference: str | None = None
    statement_currency: str | None = None
    statement_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    line_count: int
    line_resolved_count: int
    ambiguous_count: int
    state: str
    created_at: datetime


class BatchSummaryList(BaseModel):
    batches: list[BatchSummary]


class ReconciliationLinkView(BaseModel):
    outcome: str
    method: str
    confidence: float | None = None
    note: str | None = None


class ObservationView(BaseModel):
    observation_id: UUID
    source_merchant: str | None = None
    source_reference: str | None = None
    status: str
    amount_minor: int
    currency: str
    direction: str
    transaction_date: date | None = None


class StatementLineView(BaseModel):
    line_id: UUID
    line_index: int
    direction: str
    amount_minor: int
    currency: str
    merchant: str | None = None
    external_reference: str | None = None
    description: str | None = None
    transaction_date: date | None = None
    posting_date: date | None = None
    running_balance_minor: int | None = None
    event_status: str
    event_id: UUID | None = None
    reconciliation: ReconciliationLinkView | None = None
    observation: ObservationView | None = None
    eligible_observations: list[ObservationView] = Field(default_factory=list)


class FinancialAccountView(BaseModel):
    account_id: UUID
    issuer: str
    external_reference: str
    wallet_account_reference: str | None = None


class BatchDetail(BaseModel):
    batch_id: UUID
    statement_id: UUID
    state: str
    statement_status: str
    statement_currency: str | None = None
    statement_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    opening_balance_minor: int | None = None
    closing_balance_minor: int | None = None
    account: FinancialAccountView | None = None
    lines: list[StatementLineView]
    reviewer_id: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime


class FinancialEventView(BaseModel):
    event_id: UUID
    direction: str
    amount_minor: int
    currency: str
    merchant: str | None = None
    reference: str | None = None
    transaction_date: date | None = None
    posting_date: date | None = None
    event_status: str


class ResolveLineRequest(BaseModel):
    outcome: str
    observation_id: UUID | None = None
    note: str | None = None


class ResolveLineResponse(BaseModel):
    link_id: UUID
    outcome: str
    method: str
    note: str | None = None


class MapAccountRequest(BaseModel):
    wallet_account_reference: str = Field(min_length=1, max_length=255)


class MapAccountResponse(BaseModel):
    account_id: UUID
    wallet_account_reference: str


class ApproveBatchRequest(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=128)
    note: str | None = None


class ApproveBatchResponse(BaseModel):
    batch_id: UUID
    event_count: int
    events: list[FinancialEventView]


class DryRunImportResponse(BaseModel):
    command_id: UUID
    event_id: UUID
    status: str
    issued_at: datetime


class ErrorDetail(BaseModel):
    detail: str

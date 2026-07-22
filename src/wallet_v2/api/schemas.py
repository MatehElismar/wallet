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
    enrichment_overrides: dict[str, OverrideDecisionRequest] | None = None


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


# ── Advisory enrichment (Phase C) ───────────────────────────────────────────


class EvidenceRecordView(BaseModel):
    """One bounded MCP evidence record referenced by a decision/research row."""

    record_id: str | None = None
    grade: str | None = None
    score: float | None = None
    account_id: str | None = None
    record_date: str | None = None
    counter_party: str | None = None
    amount_value: float | None = None
    currency: str | None = None
    category_id: str | None = None
    label_ids: list[str] = Field(default_factory=list)
    payment_type: str | None = None


class CandidateResearchView(BaseModel):
    """Advisory-only research preview for a notification candidate.

    Never finalizable and never importable — surfaced read-only in the PWA.
    """

    candidate_id: str
    evidence_grade: str
    # Always ``False``: candidate research is advisory context only and never
    # offers a finalizable recommendation.
    recommendation: bool = False
    is_finalizable: bool = False
    selected_account_id: str | None = None
    selected_category_id: str | None = None
    selected_label_ids: list[str] = Field(default_factory=list)
    selected_payment_type: str | None = None
    rationale: str = ""
    integrity_hash: str | None = None
    query_inputs: dict[str, object] | None = None
    response_metadata: dict[str, object] | None = None
    evidence: list[EvidenceRecordView] = Field(default_factory=list)
    # ── candidate source fields (for inbox / detail views) ────────────────
    merchant: str | None = None
    reference: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    direction: str | None = None
    transaction_date: date | None = None
    candidate_status: str | None = None
    sender: str | None = None
    subject: str | None = None
    source_date: datetime | None = None


class EventEnrichmentView(BaseModel):
    """The current (latest-version) enrichment decision for a line item or canonical event."""

    line_id: str | None = None
    event_id: str | None = None
    version: int
    evidence_grade: str
    recommendation: bool
    finalized: bool
    can_finalize: bool
    selected_account_id: str | None = None
    selected_category_id: str | None = None
    selected_label_ids: list[str] = Field(default_factory=list)
    selected_payment_type: str | None = None
    rationale: str = ""
    query_inputs: dict[str, object] | None = None
    evidence_refs: dict[str, object] | None = None
    catalog_snapshot_ids: dict[str, object] | None = None
    provenance: dict[str, object] | None = None
    created_at: datetime | None = None


class OverrideDecisionRequest(BaseModel):
    """Explicit operator override that creates a new immutable version."""

    account_id: str = Field(min_length=1, max_length=255)
    category_id: str | None = Field(default=None, max_length=255)
    label_ids: list[str] = Field(default_factory=list)
    payment_type: str | None = Field(default=None, max_length=64)


class DryRunRecordPreview(BaseModel):
    """Exact Wallet REST create-record payload for a finalized decision.

    ``submitted`` is always ``False``: this endpoint never writes to Wallet.
    """

    event_id: str
    decision_version: int
    submitted: bool = False
    payload: dict[str, object]
    catalog_snapshot_ids: dict[str, object] | None = None


class PushConfigResponse(BaseModel):
    """Runtime push configuration exposed to the PWA frontend."""

    enabled: bool
    public_key: str | None = None
    fcm_project_id: str | None = None


class RegisterSubscriptionRequest(BaseModel):
    """Browser Push API subscription payload."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys_p256dh: str = Field(min_length=1)
    keys_auth: str = Field(min_length=1)
    user_agent: str | None = Field(None, max_length=512)


class RegisterSubscriptionResponse(BaseModel):
    subscription_id: UUID
    status: str


class DisableSubscriptionResponse(BaseModel):
    subscription_id: UUID
    status: str


class SubscriptionStatusResponse(BaseModel):
    active_count: int
    disabled_count: int
    subscriptions: list["SubscriptionView"]


class SubscriptionView(BaseModel):
    subscription_id: UUID
    endpoint: str
    status: str
    created_at: datetime
    disabled_at: datetime | None = None
    disabled_reason: str | None = None

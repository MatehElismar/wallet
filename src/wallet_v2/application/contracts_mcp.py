"""Transport-neutral MCP advisory DTOs and protocol.

Every data class is frozen and slotted. The protocol defines only the five
allowlisted read-only operations, with no generic ``call_tool`` surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


# ── Shared sub-types ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class McpCategory:
    id: str
    name: str = ""


@dataclass(frozen=True, slots=True)
class McpLabel:
    id: str
    name: str = ""


# ── get_client_profile ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class McpClientProfile:
    sync_state: str
    granted_scopes: tuple[str, ...]
    synced_at: str | None = None
    raw_profile: dict[str, object] | None = None


# ── get_records ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class McpRecord:
    id: str
    account_id: str
    amount_value: float
    currency: str
    record_date: str
    counter_party: str | None = None
    category: McpCategory | None = None
    labels: tuple[McpLabel, ...] = ()
    payment_type: str | None = None
    record_state: str | None = None
    source: str | None = None
    account_is_bank_sync: bool | None = None


@dataclass(frozen=True, slots=True)
class McpRecordsResult:
    records: tuple[McpRecord, ...] = ()
    total: int | None = None
    offset: int = 0
    limit: int = 200
    next_offset: int | None = None


# ── get_records_aggregation ───────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class McpAggregationRow:
    key: str
    value: float
    count: int


@dataclass(frozen=True, slots=True)
class McpAggregationResult:
    results: tuple[McpAggregationRow, ...] = ()
    offset: int = 0
    limit: int = 200
    base_currency: str | None = None
    transfers_included: bool | None = None


# ── get_budgets ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class McpBudget:
    id: str
    name: str
    period: str
    amount: float
    spent: float | None = None
    remaining: float | None = None


@dataclass(frozen=True, slots=True)
class McpBudgetsResult:
    budgets: tuple[McpBudget, ...] = ()
    total: int | None = None
    limit: int = 200
    offset: int = 0


# ── get_entity (documentType) ──────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class McpEntityResult:
    document_type: str
    results: tuple[dict[str, object], ...] = ()
    limit: int = 200
    offset: int = 0


# ── Response metadata (from _meta) ────────────────────────────────────


@dataclass(frozen=True, slots=True)
class McpResponseMeta:
    synced_at: str | None = None
    last_resource_change: str | None = None
    rate_limit_remaining: int | None = None
    rate_limit_capacity: int | None = None
    rate_limit_refill_per_minute: int | None = None


# ── Protocol ──────────────────────────────────────────────────────────


class McpReadOnlyClient(Protocol):
    """Typed read-only MCP adapter contract.

    No generic ``call_tool`` method exists. Every operation has an explicit
    typed method that is statically visible at the call site.
    """

    def get_client_profile(self) -> McpClientProfile: ...

    def get_records(
        self,
        *,
        account_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> McpRecordsResult: ...

    def get_records_aggregation(
        self,
        *,
        account_id: str,
        group_by: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> McpAggregationResult: ...

    def get_budgets(
        self,
        *,
        account_id: str,
    ) -> McpBudgetsResult: ...

    def get_entity(
        self,
        *,
        document_type: Literal["record_rules"],
        limit: int = 200,
        offset: int = 0,
    ) -> McpEntityResult: ...

    @property
    def last_response_meta(self) -> McpResponseMeta: ...

    @property
    def profile_validated(self) -> bool: ...

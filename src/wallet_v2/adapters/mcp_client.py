"""Streamable HTTP typed MCP client — advisory read-only only.

No generic ``call_tool`` public API exists. The adapter enforces a fixed
internal allowlist and rejects any method outside it before serialising a
network request. The profile gate requires ``syncState=complete`` and the
observed dot-read scopes needed for each typed operation.

``dry_run`` mode permits live read-only queries (network I/O for GET-like
operations) but the adapter never writes — it has no write-tool surface.
``dry_run`` is *not* a no-network mode; it disables only the downstream
Wallet submission path, not MCP advisory queries.
"""

from __future__ import annotations

import datetime
import json
import socket
import uuid
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from wallet_v2.application.contracts_mcp import (
    McpAggregationResult,
    McpAggregationRow,
    McpBudget,
    McpBudgetsResult,
    McpCategory,
    McpClientProfile,
    McpEntityResult,
    McpLabel,
    McpRecord,
    McpRecordsResult,
    McpResponseMeta,
)


class WalletMcpClient:
    """Typed, read-only MCP client with an explicit operation allowlist.

    The adapter never exposes a generic ``call_tool`` method. Every typed
    operation is a separate public method. The internal ``_call`` helper is
    private and rejects any tool name outside ``ALLOWED_TOOLS``.

    ``dry_run`` vs ``live``: both modes permit live read-only MCP queries
    (network I/O). ``dry_run`` disables only the downstream Wallet
    submission path. MCP queries are always advisory and read-only; the
    adapter has no write-tool surface.

    Design invariants:

    * ``get_client_profile`` must be called first. It validates
      ``syncState=complete`` and records the observed dot-read scopes.
    * After profile validation each typed method checks that the required
      scope was granted.
    * The profile is cached on the instance; the caller should call
      ``get_client_profile`` once at the start of a run.
    * All tool names are checked against ``ALLOWED_TOOLS`` before any
      network I/O.
    """

    ALLOWED_TOOLS: frozenset[str] = frozenset({
        "get_client_profile",
        "get_records",
        "get_records_aggregation",
        "get_budgets",
        "get_entity",
    })

    _REQUIRED_SCOPES: dict[str, str] = {
        "get_records": "records.read",
        "get_records_aggregation": "records.read",
        "get_budgets": "budgets.read",
        "get_entity": "record_rules.read",
    }

    def __init__(
        self, *, base_url: str, api_key: str, timeout_seconds: float
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._profile_validated: bool = False
        self._observed_scopes: tuple[str, ...] = ()
        self._profile_sync_state: str | None = None
        self._last_meta: McpResponseMeta = McpResponseMeta()

    # ── public properties ─────────────────────────────────────────────

    @property
    def profile_validated(self) -> bool:
        """Whether ``get_client_profile`` succeeded the profile gate."""
        return self._profile_validated

    @property
    def last_response_meta(self) -> McpResponseMeta:
        """Metadata from the most recent MCP response."""
        return self._last_meta

    @property
    def observed_scopes(self) -> tuple[str, ...]:
        """Scopes observed in the last profile response."""
        return self._observed_scopes

    # ── get_client_profile ────────────────────────────────────────────

    def get_client_profile(self) -> McpClientProfile:
        raw = self._call("get_client_profile")
        sync_state = str(raw.get("syncState", "")).lower()
        raw_scopes = raw.get("grantedScopes")
        scopes: tuple[str, ...] = ()
        if isinstance(raw_scopes, list):
            scopes = tuple(str(s) for s in raw_scopes if isinstance(s, str))

        if sync_state != "complete":
            raise ValueError(
                f"MCP profile syncState is {sync_state!r}, expected 'complete'"
            )

        self._profile_validated = True
        self._observed_scopes = scopes
        self._profile_sync_state = sync_state

        return McpClientProfile(
            sync_state=sync_state,
            granted_scopes=scopes,
            synced_at=self._last_meta.synced_at,
            raw_profile=raw,
        )

    # ── get_records ───────────────────────────────────────────────────

    def get_records(
        self,
        *,
        account_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> McpRecordsResult:
        if not account_id:
            raise ValueError("account_id must not be empty")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if limit > 500:
            raise ValueError("limit must be <= 500")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        self._validate_date_range(date_from, date_to)

        params: dict[str, object] = {"accountId": account_id}
        if date_from is not None or date_to is not None:
            record_date: list[str] = []
            if date_from is not None:
                record_date.append(f"gte.{date_from}")
            if date_to is not None:
                record_date.append(f"lt.{date_to}")
            params["recordDate"] = record_date
        params["limit"] = limit
        params["offset"] = offset

        raw = self._call("get_records", params)
        raw_records: list[dict[str, object]] = []
        if isinstance(raw.get("records"), list):
            raw_records = raw["records"]
        total: int | None = raw.get("total")
        if not isinstance(total, int):
            total = None
        ret_offset = int(raw.get("offset", offset))
        ret_limit = int(raw.get("limit", limit))
        next_offset: int | None = raw.get("nextOffset")
        if not isinstance(next_offset, int):
            next_offset = None

        records = tuple(self._parse_record(r) for r in raw_records)
        return McpRecordsResult(
            records=records,
            total=total,
            offset=ret_offset,
            limit=ret_limit,
            next_offset=next_offset,
        )

    # ── get_records_aggregation ───────────────────────────────────────

    def get_records_aggregation(
        self,
        *,
        account_id: str,
        group_by: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> McpAggregationResult:
        if not account_id:
            raise ValueError("account_id must not be empty")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if limit > 500:
            raise ValueError("limit must be <= 500")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        self._validate_date_range(date_from, date_to)

        params: dict[str, object] = {
            "accountId": account_id,
            "groupBy": [group_by],
        }
        if date_from is not None or date_to is not None:
            record_date: list[str] = []
            if date_from is not None:
                record_date.append(f"gte.{date_from}")
            if date_to is not None:
                record_date.append(f"lt.{date_to}")
            params["recordDate"] = record_date
        params["limit"] = limit
        params["offset"] = offset

        raw = self._call("get_records_aggregation", params)
        raw_results: list[dict[str, object]] = []
        if isinstance(raw.get("results"), list):
            raw_results = raw["results"]
        ret_offset = int(raw.get("offset", offset))
        ret_limit = int(raw.get("limit", limit))
        base_currency = raw.get("baseCurrency")
        transfers_included: bool | None = raw.get("transfersIncluded")
        if not isinstance(transfers_included, bool):
            transfers_included = None

        results = tuple(
            McpAggregationRow(
                key=str(b["key"]),
                value=float(b.get("value", 0)),
                count=int(b.get("count", 0)),
            )
            for b in raw_results
        )
        return McpAggregationResult(
            results=results,
            offset=ret_offset,
            limit=ret_limit,
            base_currency=str(base_currency) if isinstance(base_currency, str) else None,
            transfers_included=transfers_included,
        )

    # ── get_budgets ───────────────────────────────────────────────────

    def get_budgets(self, *, account_id: str) -> McpBudgetsResult:
        if not account_id:
            raise ValueError("account_id must not be empty")

        raw = self._call("get_budgets", {"accountId": account_id})
        raw_budgets: list[dict[str, object]] = []
        if isinstance(raw.get("budgets"), list):
            raw_budgets = raw["budgets"]

        if len(raw_budgets) > 1000:
            raise ValueError(
                f"MCP budgets response has {len(raw_budgets)} entries, "
                f"exceeds hard cap of 1000"
            )

        total: int | None = raw.get("total")
        if not isinstance(total, int):
            total = None
        ret_offset = int(raw.get("offset", 0))
        ret_limit = int(raw.get("limit", 200))

        budgets = tuple(
            McpBudget(
                id=str(b["id"]),
                name=str(b.get("name", "")),
                period=str(b.get("period", "")),
                amount=float(b.get("amount", 0)),
                spent=float(b["spent"]) if b.get("spent") is not None else None,
                remaining=float(b["remaining"]) if b.get("remaining") is not None else None,
            )
            for b in raw_budgets
        )
        return McpBudgetsResult(
            budgets=budgets, total=total, limit=ret_limit, offset=ret_offset,
        )

    # ── get_entity (documentType) ─────────────────────────────────────

    def get_entity(
        self,
        *,
        document_type: Literal["record_rules"],
        limit: int = 200,
        offset: int = 0,
    ) -> McpEntityResult:
        if document_type != "record_rules":
            raise ValueError(
                f"disallowed entity document_type {document_type!r}; "
                f"only 'record_rules' is allowed"
            )
        params: dict[str, object] = {"documentType": "record-rules"}
        if limit:
            params["limit"] = limit
        if offset > 0:
            params["offset"] = offset
        raw = self._call("get_entity", params)
        raw_results: list[dict[str, object]] = []
        if isinstance(raw.get("results"), list):
            raw_results = raw["results"]
        ret_limit = int(raw.get("limit", limit))
        ret_offset = int(raw.get("offset", offset))

        return McpEntityResult(
            document_type=str(raw.get("documentType", "record-rules")),
            results=tuple(dict(r) for r in raw_results),
            limit=ret_limit,
            offset=ret_offset,
        )

    # ── private helpers ───────────────────────────────────────────────

    def _call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        """Send a JSON-RPC 2.0 request and return the structuredContent dict.

        This method is private. It rejects any tool name not in the fixed
        allowlist *before* serialising a network request — the fail-closed
        invariant.
        """
        if method not in self.ALLOWED_TOOLS:
            raise ValueError(
                f"disallowed MCP tool: {method!r}; "
                f"allowed: {sorted(self.ALLOWED_TOOLS)}"
            )

        if method != "get_client_profile":
            self._ensure_profile_gate(method)

        request_id = str(uuid.uuid4())
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": method, "arguments": params or {}},
                "id": request_id,
            }
        ).encode("utf-8")

        req = Request(
            self._base_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
        )

        try:
            with urlopen(req, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
                try:
                    data: object = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"MCP response is not valid JSON: {exc.msg}"
                    ) from exc
                if not isinstance(data, dict):
                    raise ValueError("MCP response must be a JSON object")
                if data.get("jsonrpc") != "2.0":
                    raise ValueError(
                        f"MCP response must use JSON-RPC 2.0, got {data.get('jsonrpc')!r}"
                    )
                if data.get("id") != request_id:
                    raise ValueError(
                        f"MCP response id {data.get('id')!r} does not match "
                        f"request id {request_id!r}"
                    )
                if "error" in data:
                    err = data["error"]
                    code = err.get("code", -1)
                    message = err.get("message", "unknown error")
                    raise ValueError(
                        f"MCP error {code}: {message}"
                    )
                result = data.get("result")
                if not isinstance(result, dict):
                    raise ValueError("MCP result must be a JSON object")
                structured = result.get("structuredContent")
                if not isinstance(structured, dict):
                    raise ValueError(
                        "MCP result must contain a structuredContent object"
                    )
                self._last_meta = self._parse_meta(structured.get("_meta"))
                return structured
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:4096]
            raise ValueError(
                f"MCP HTTP {exc.code}: {error_body}"
            ) from exc
        except TimeoutError as exc:
            raise TimeoutError("MCP request timed out") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("MCP request timed out") from exc
            raise ConnectionError(
                f"MCP connection failed: {exc.reason}"
            ) from exc

    def _ensure_profile_gate(self, method: str) -> None:
        if not self._profile_validated:
            raise RuntimeError(
                "MCP profile not validated; call get_client_profile first"
            )
        required = self._REQUIRED_SCOPES.get(method)
        if required and required not in self._observed_scopes:
            raise PermissionError(
                f"MCP scope {required!r} required for {method!r} "
                f"but not in observed scopes: {self._observed_scopes}"
            )

    @staticmethod
    def _parse_iso_date(value: str, field: str) -> datetime.date:
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"{field} must be a non-empty ISO 8601 date string"
            )
        try:
            return datetime.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"{field} {value!r} is not a valid ISO 8601 date"
            ) from exc

    def _validate_date_range(
        self, date_from: str | None, date_to: str | None
    ) -> None:
        """Validate date_from/date_to as ISO 8601 dates with sane ordering.

        ``date_from`` is inclusive lower bound; ``date_to`` is exclusive
        upper bound. Both are optional, but when both are present
        ``date_from`` must not be later than ``date_to``.
        """
        parsed_from: datetime.date | None = None
        parsed_to: datetime.date | None = None
        if date_from is not None:
            parsed_from = self._parse_iso_date(date_from, "date_from")
        if date_to is not None:
            parsed_to = self._parse_iso_date(date_to, "date_to")
        if (
            parsed_from is not None
            and parsed_to is not None
            and parsed_from > parsed_to
        ):
            raise ValueError(
                f"date_from {date_from!r} must not be later than "
                f"date_to {date_to!r}"
            )

    @staticmethod
    def _parse_meta(meta_raw: object) -> McpResponseMeta:
        if not isinstance(meta_raw, dict):
            return McpResponseMeta()
        synced_at = meta_raw.get("syncedAt")
        last_resource_change = meta_raw.get("lastResourceChange")
        rate_limit_raw = meta_raw.get("rateLimit")
        rate_limit_remaining: int | None = None
        rate_limit_capacity: int | None = None
        rate_limit_refill: int | None = None
        if isinstance(rate_limit_raw, dict):
            r = rate_limit_raw
            if isinstance(r.get("remaining"), int):
                rate_limit_remaining = r["remaining"]
            if isinstance(r.get("capacity"), int):
                rate_limit_capacity = r["capacity"]
            if isinstance(r.get("refillPerMinute"), int):
                rate_limit_refill = r["refillPerMinute"]
        return McpResponseMeta(
            synced_at=str(synced_at) if isinstance(synced_at, str) and synced_at else None,
            last_resource_change=(
                str(last_resource_change)
                if isinstance(last_resource_change, str) and last_resource_change
                else None
            ),
            rate_limit_remaining=rate_limit_remaining,
            rate_limit_capacity=rate_limit_capacity,
            rate_limit_refill_per_minute=rate_limit_refill,
        )

    @staticmethod
    def _parse_record(data: dict[str, object]) -> McpRecord:
        amount_raw = data.get("amount")
        if not isinstance(amount_raw, dict):
            raise ValueError(
                f"MCP record missing or invalid 'amount' field: "
                f"expected dict, got {type(amount_raw).__name__}"
            )
        val = amount_raw.get("value")
        if not isinstance(val, (int, float)):
            raise ValueError(
                f"MCP record 'amount.value' is missing or non-numeric: {val!r}"
            )
        amount_value = float(val)
        currency = amount_raw.get("currencyCode")
        if not isinstance(currency, str) or not currency:
            raise ValueError(
                f"MCP record 'amount.currencyCode' is missing or not a string: {currency!r}"
            )

        labels_raw = data.get("labels")
        labels: tuple[McpLabel, ...] = ()
        if isinstance(labels_raw, list):
            labels = tuple(
                McpLabel(
                    id=str(l["id"]),
                    name=str(l.get("name", "")),
                )
                for l in labels_raw
                if isinstance(l, dict) and "id" in l
            )

        category_raw = data.get("category")
        category: McpCategory | None = None
        if isinstance(category_raw, dict) and "id" in category_raw:
            category = McpCategory(
                id=str(category_raw["id"]),
                name=str(category_raw.get("name", "")),
            )

        source_raw = data.get("source")
        source: str | None = str(source_raw) if isinstance(source_raw, str) else None

        account_bank_sync_raw = data.get("accountIsBankSync")
        account_bank_sync: bool | None = (
            bool(account_bank_sync_raw)
            if isinstance(account_bank_sync_raw, bool)
            else None
        )

        return McpRecord(
            id=str(data.get("id", "")),
            account_id=str(data.get("accountId", "")),
            amount_value=amount_value,
            currency=currency,
            record_date=str(data.get("recordDate", "")),
            counter_party=str(data["counterParty"])
            if data.get("counterParty")
            else None,
            category=category,
            labels=labels,
            payment_type=str(data["paymentType"])
            if data.get("paymentType")
            else None,
            record_state=str(data["recordState"])
            if data.get("recordState")
            else None,
            source=source,
            account_is_bank_sync=account_bank_sync,
        )

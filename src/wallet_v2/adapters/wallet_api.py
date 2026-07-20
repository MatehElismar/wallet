"""BudgetBakers Wallet API adapter with explicit result classification.

Provides typed read operations for the Wallet catalog (accounts,
categories, labels, record rules, records) and parse-only batch create
response handling. Write submission is retained for the existing legacy
workflow; batch response parsing is exposed as a contract capability
but writes are not invoked from this code path.
"""

from __future__ import annotations

import json
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from wallet_v2.application.contracts import (
    BatchCreateResult,
    CreateRecordResponseItem,
    WalletAccount,
    WalletAmount,
    WalletBalance,
    WalletCatalogRef,
    WalletCategory,
    WalletLabel,
    WalletRecord,
    WalletRecordRule,
    WalletRecordTransfer,
    WalletSubmissionResult,
)
from wallet_v2.domain.enums import WalletAttemptStatus


class BudgetBakersWalletClient:
    """Submit one record and read catalog entities from the Wallet REST API.

    This client is intentionally used only by a live application run. Dry-run
    behavior is enforced by the application service before this method can be
    called, so there is no hidden network fallback here.

    Read operations use GET on the documented REST endpoints. Batch create
    response parsing is a static capability exposed for protocol conformance;
    it does not invoke writes.
    """

    _RATE_LIMIT_HTTP_CODE = 429
    _RESOURCE_KEYS: dict[str, str] = {
        "/v1/api/accounts": "accounts",
        "/v1/api/categories": "categories",
        "/v1/api/labels": "labels",
        "/v1/api/record-rules": "recordRules",
        "/v1/api/records": "records",
    }

    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._last_response_meta: dict[str, str] = {}

    # ── helpers ──────────────────────────────────────────────────────

    def _get(self, path: str) -> list[dict[str, object]]:
        """Read every documented page for one catalog endpoint.

        Wallet supplies ``nextOffset`` only when a following page exists. A
        malformed envelope or a non-advancing offset is a contract failure:
        returning a partial catalog would make later account/category mapping
        unsafe.
        """
        parsed = urlsplit(path)
        base_path = parsed.path
        resource_key = self._RESOURCE_KEYS.get(base_path)
        if resource_key is None:
            raise ValueError(f"Unsupported Wallet catalog path: {base_path!r}")

        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["limit"] = "200"
        offset = 0
        seen_offsets: set[int] = set()
        items: list[dict[str, object]] = []

        while True:
            if offset in seen_offsets:
                raise ValueError("Wallet pagination repeated an offset")
            seen_offsets.add(offset)
            query["offset"] = str(offset)
            page_path = urlunsplit(("", "", base_path, urlencode(query), ""))
            page_items, next_offset = self._get_page(
                page_path=page_path,
                resource_key=resource_key,
            )
            items.extend(page_items)
            if next_offset is None:
                return items
            if next_offset <= offset:
                raise ValueError("Wallet pagination did not advance offset")
            offset = next_offset

    def _get_page(
        self, *, page_path: str, resource_key: str
    ) -> tuple[list[dict[str, object]], int | None]:
        request = Request(
            f"{self.base_url}{page_path}",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            self._last_response_meta = {
                "x_last_data_change_rev": response.headers.get("X-Last-Data-Change-Rev", ""),
                "x_last_data_change_at": response.headers.get("X-Last-Data-Change-At", ""),
                "x_sync_in_progress": response.headers.get("X-Sync-In-Progress", ""),
                "x_ratelimit_limit": response.headers.get("X-RateLimit-Limit", ""),
                "x_ratelimit_remaining": response.headers.get("X-RateLimit-Remaining", ""),
            }
            if not isinstance(data, dict):
                raise ValueError("Wallet catalog response must be an object")
            raw_items = data.get(resource_key)
            if not isinstance(raw_items, list) or not all(
                isinstance(item, dict) for item in raw_items
            ):
                raise ValueError(
                    f"Wallet catalog response missing list field {resource_key!r}"
                )
            next_offset = data.get("nextOffset")
            if next_offset is None:
                return raw_items, None
            if isinstance(next_offset, bool) or not isinstance(next_offset, int):
                raise ValueError("Wallet catalog response has invalid nextOffset")
            return raw_items, next_offset

    def has_sync_in_progress(self) -> bool:
        return self._last_response_meta.get("x_sync_in_progress", "").lower() == "true"

    def last_revision(self) -> str | None:
        rev = self._last_response_meta.get("x_last_data_change_rev", "")
        return rev if rev else None

    # ── catalog read operations ──────────────────────────────────────

    def get_accounts(self) -> Sequence[WalletAccount]:
        data = self._get("/v1/api/accounts")
        return tuple(self._parse_account(item) for item in data)

    def get_categories(self) -> Sequence[WalletCategory]:
        data = self._get("/v1/api/categories")
        return tuple(self._parse_category(item) for item in data)

    def get_labels(self) -> Sequence[WalletLabel]:
        data = self._get("/v1/api/labels")
        return tuple(self._parse_label(item) for item in data)

    def get_record_rules(self) -> Sequence[WalletRecordRule]:
        data = self._get("/v1/api/record-rules")
        return tuple(self._parse_record_rule(item) for item in data)

    def get_records(self) -> Sequence[WalletRecord]:
        data = self._get("/v1/api/records")
        return tuple(self._parse_record(item) for item in data)

    def get_records_by_account(self, *, account_id: str) -> Sequence[WalletRecord]:
        data = self._get(f"/v1/api/records?{urlencode({'accountId': account_id})}")
        return tuple(self._parse_record(item) for item in data)

    # ── static parsers (no network, usable from tests / fixtures) ────

    @staticmethod
    def _parse_account(data: dict[str, object]) -> WalletAccount:
        balance_raw = data.get("balance")
        balance: WalletBalance | None = None
        if isinstance(balance_raw, dict):
            balance = WalletBalance(
                currency_code=str(balance_raw["currencyCode"]),
                value=float(balance_raw["currentBalance"]),
            )
        initial_raw = data.get("initialBalance")
        initial_balance: WalletBalance | None = None
        if isinstance(initial_raw, dict):
            initial_balance = WalletBalance(
                currency_code=str(initial_raw["currencyCode"]),
                value=float(initial_raw["value"]),
            )
        return WalletAccount(
            id=str(data["id"]),
            name=str(data["name"]),
            archived=bool(data.get("archived", False)),
            exclude_from_stats=bool(data.get("excludeFromStats", False)),
            balance=balance,
            initial_balance=initial_balance,
        )

    @staticmethod
    def _parse_category(data: dict[str, object]) -> WalletCategory:
        return WalletCategory(
            id=str(data["id"]),
            name=str(data["name"]),
            color=str(data["color"]) if data.get("color") else None,
            archived=bool(data.get("archived", False)),
            parent_id=str(data["parentId"]) if data.get("parentId") else None,
        )

    @staticmethod
    def _parse_label(data: dict[str, object]) -> WalletLabel:
        return WalletLabel(
            id=str(data["id"]),
            name=str(data["name"]),
            color=str(data["color"]) if data.get("color") else None,
            archived=bool(data.get("archived", False)),
        )

    @staticmethod
    def _parse_record_rule(data: dict[str, object]) -> WalletRecordRule:
        category = BudgetBakersWalletClient._parse_catalog_ref(data.get("category"))
        labels_raw = data.get("labels")
        labels: tuple[WalletCatalogRef, ...] = ()
        if isinstance(labels_raw, list):
            labels = tuple(
            ref
            for item in labels_raw
            if (ref := BudgetBakersWalletClient._parse_catalog_ref(item)) is not None
            )
        keywords_raw = data.get("keywords")
        keywords: tuple[str, ...] = ()
        if isinstance(keywords_raw, list):
            keywords = tuple(str(k) for k in keywords_raw)
        return WalletRecordRule(
            id=str(data["id"]),
            name=str(data["name"]) if data.get("name") else None,
            keywords=keywords,
            category=category,
            labels=labels,
            from_account_id=str(data["fromAccountId"]) if data.get("fromAccountId") else None,
            to_account_id=str(data["toAccountId"]) if data.get("toAccountId") else None,
        )

    @staticmethod
    def _parse_record(data: dict[str, object]) -> WalletRecord:
        amount_raw = data.get("amount") or {}
        amount = WalletAmount(
            value=float(amount_raw["value"]),  # type: ignore[index]
            currency_code=str(amount_raw["currencyCode"]),  # type: ignore[index]
        )
        category = BudgetBakersWalletClient._parse_catalog_ref(data.get("category"))
        labels_raw = data.get("labels")
        labels: tuple[WalletCatalogRef, ...] = ()
        if isinstance(labels_raw, list):
            labels = tuple(
            ref
            for item in labels_raw
            if (ref := BudgetBakersWalletClient._parse_catalog_ref(item)) is not None
            )
        transfer: WalletRecordTransfer | None = None
        transfer_raw = data.get("transfer")
        if isinstance(transfer_raw, dict):
            mirror = BudgetBakersWalletClient._parse_catalog_ref(
                transfer_raw.get("mirrorRecord")
            )
            transfer = WalletRecordTransfer(
                type=str(transfer_raw["type"]) if transfer_raw.get("type") else None,
                mirror_record=mirror,
            )
        return WalletRecord(
            id=str(data["id"]),
            account_id=str(data["accountId"]),
            amount=amount,
            record_date=str(data["recordDate"]),
            category=category,
            counter_party=str(data["counterParty"]) if data.get("counterParty") else None,
            labels=labels,
            payment_type=str(data["paymentType"]) if data.get("paymentType") else None,
            record_type=str(data["recordType"]) if data.get("recordType") else None,
            record_state=str(data["recordState"]) if data.get("recordState") else None,
            transfer=transfer,
        )

    @staticmethod
    def _parse_catalog_ref(value: object) -> WalletCatalogRef | None:
        if not isinstance(value, dict):
            return None
        identifier = value.get("id")
        if not isinstance(identifier, str) or not identifier:
            return None
        return WalletCatalogRef(id=identifier)

    # ── batch create response parsing (contract capability, no writes) ──

    @staticmethod
    def parse_batch_create_response(
        *, raw_response: list[dict[str, object]]
    ) -> BatchCreateResult:
        """Parse a batch create response into per-index results.

        Supports two documented Wallet REST response shapes:

        * **200 (flat list):** ``[{id, recordId, ...}, ...]``
          Each item is a successfully created record, indexed by position.

        * **207 (mixed):** ``{results: [{index, status, record?, error?}, ...]}``
          Each result has an explicit ``index``, ``status``, and optional
          ``record`` or ``error``.
        """
        if not raw_response:
            return BatchCreateResult()

        first = raw_response[0]
        if "results" in first:
            # 207 mixed response: {'results': [...]}
            results_raw = first.get("results")
            if not isinstance(results_raw, list):
                return BatchCreateResult()
            items: list[CreateRecordResponseItem] = []
            for entry in results_raw:
                if not isinstance(entry, dict):
                    continue
                idx = int(entry.get("index", 0))
                status = int(entry.get("status", 0))
                record = entry.get("record")
                error = entry.get("error")
                record_id: str | None = None
                error_code: str | None = None
                error_message: str | None = None
                if isinstance(record, dict):
                    for key in ("recordId", "id"):
                        val = record.get(key)
                        if val is not None:
                            record_id = str(val)
                            break
                if isinstance(error, dict):
                    error_code = str(error.get("code")) if error.get("code") else None
                    error_message = str(error.get("message")) if error.get("message") else None
                items.append(
                    CreateRecordResponseItem(
                        index=idx,
                        status=status,
                        record_id=record_id,
                        error_code=error_code,
                        error_message=error_message,
                    )
                )
            return BatchCreateResult(items=tuple(items))
        else:
            # 200 flat list response: each item is a single success
            items: list[CreateRecordResponseItem] = []
            for idx, entry in enumerate(raw_response):
                if not isinstance(entry, dict):
                    continue
                record_id = None
                for key in ("recordId", "id"):
                    val = entry.get(key)
                    if val is not None:
                        record_id = str(val)
                        break
                items.append(
                    CreateRecordResponseItem(
                        index=idx,
                        status=200,
                        record_id=record_id,
                    )
                )
            return BatchCreateResult(items=tuple(items))

    # ── rate-limit classification (static, usable from tests) ────────

    @staticmethod
    def classify_rate_limit(
        *, response_body: dict[str, object] | None = None, status_code: int = 0
    ) -> str | None:
        """Classify a response as a rate-limit scenario.

        Returns an error classification string when a rate limit is
        detected, or ``None`` otherwise.
        """
        if status_code == BudgetBakersWalletClient._RATE_LIMIT_HTTP_CODE:
            return "rate_limit"
        if response_body and isinstance(response_body.get("error"), dict):
            code = response_body["error"].get("code")  # type: ignore[index]
            if code == "RATE_LIMIT_EXCEEDED":
                return "rate_limit"
        return None

    # ── legacy submit (preserved) ────────────────────────────────────

    def submit(
        self, *, idempotency_key: str, payload: dict[str, object]
    ) -> WalletSubmissionResult:
        request_payload = [payload]
        body = json.dumps(request_payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/v1/api/records",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310 -- configured endpoint
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
                provider_id = self._provider_transaction_id(data)
                batch_result = self._parse_batch_result_from_raw(data)
                return WalletSubmissionResult(
                    status=WalletAttemptStatus.ACKNOWLEDGED,
                    request=payload,
                    response=data if isinstance(data, dict) else {"results": data},
                    provider_transaction_id=provider_id,
                    batch_result=batch_result,
                )
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:2048]
            error_data: dict[str, object] | None = None
            try:
                error_data = json.loads(error_body) if error_body else None
            except json.JSONDecodeError:
                pass
            return WalletSubmissionResult(
                status=WalletAttemptStatus.FAILED,
                request=payload,
                response=error_data,
                error_kind=f"http_{exc.code}",
                error_message=error_body,
            )
        except TimeoutError:
            return WalletSubmissionResult(
                status=WalletAttemptStatus.UNKNOWN,
                request=payload,
                response=None,
                error_kind="timeout",
                error_message="Wallet request timed out; reconciliation required",
            )
        except URLError as exc:
            return WalletSubmissionResult(
                status=WalletAttemptStatus.UNKNOWN,
                request=payload,
                response=None,
                error_kind="network",
                error_message=str(exc.reason)[:2048],
            )

    @staticmethod
    def _parse_batch_result_from_raw(
        raw: object,
    ) -> BatchCreateResult | None:
        if isinstance(raw, list):
            return BudgetBakersWalletClient.parse_batch_create_response(
                raw_response=raw  # type: ignore[arg-type]
            )
        return None

    @staticmethod
    def _provider_transaction_id(data: object) -> str | None:
        first = data[0] if isinstance(data, list) and data else data
        if not isinstance(first, dict):
            return None
        for key in ("id", "recordId", "transactionId"):
            value = first.get(key)
            if value is not None:
                return str(value)
        return None

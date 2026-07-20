"""Adapter contracts and transport-neutral workflow values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, Sequence

from wallet_v2.domain.enums import (
    DocumentKind,
    FinancialEventStatus,
    TransactionDirection,
    WalletAttemptStatus,
)


@dataclass(frozen=True, slots=True)
class MailboxMessage:
    provider: str
    account_fingerprint: str
    folder: str
    uid_validity: int
    message_uid: int
    sender: str | None
    recipient: str | None
    subject: str | None
    message_id_header: str | None
    received_at: datetime
    body_text: str


@dataclass(frozen=True, slots=True)
class ExtractedTransaction:
    direction: TransactionDirection
    amount_minor: int
    currency: str
    merchant: str | None = None
    reference: str | None = None
    transaction_date: date | None = None
    posting_date: date | None = None
    running_balance_minor: int | None = None
    issuer: str | None = None
    account_reference: str | None = None
    event_status: FinancialEventStatus = FinancialEventStatus.POSTED
    related_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedStatement:
    """Document-level fields that make a periodic statement reconcilable."""

    issuer: str
    account_reference: str
    period_start: date | None = None
    period_end: date | None = None
    statement_date: date | None = None
    currency: str | None = None
    opening_balance_minor: int | None = None
    closing_balance_minor: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    is_transaction: bool
    transaction: ExtractedTransaction | None
    raw_response: dict[str, object] | None
    structured_output: dict[str, object] | None
    model_id: str | None
    transactions: tuple[ExtractedTransaction, ...] = ()
    document_kind: DocumentKind | None = None
    statement: ExtractedStatement | None = None
    model_version: str | None = None
    token_usage: dict[str, object] | None = None

    def __post_init__(self) -> None:
        transactions = self.transactions or ((self.transaction,) if self.transaction else ())
        if self.is_transaction != bool(transactions):
            raise ValueError("is_transaction must agree with extracted transactions")
        document_kind = self.document_kind
        if document_kind is None and transactions:
            document_kind = (
                DocumentKind.STATEMENT if self.statement else DocumentKind.NOTIFICATION
            )
        if document_kind == DocumentKind.STATEMENT and self.statement is None:
            raise ValueError("statement extraction must include statement metadata")
        if document_kind != DocumentKind.STATEMENT and self.statement is not None:
            raise ValueError("statement metadata requires statement document kind")
        if document_kind is not None and not transactions:
            raise ValueError("document kind requires one or more extracted transactions")
        object.__setattr__(self, "transactions", transactions)
        object.__setattr__(self, "transaction", transactions[0] if transactions else None)
        object.__setattr__(self, "document_kind", document_kind)


# ────────────────────────────────────────────────────────────
# Wallet catalog DTOs — read from GET endpoints
# ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WalletBalance:
    currency_code: str
    value: float


@dataclass(frozen=True, slots=True)
class WalletCatalogRef:
    id: str


@dataclass(frozen=True, slots=True)
class WalletAccount:
    id: str
    name: str
    archived: bool = False
    exclude_from_stats: bool = False
    balance: WalletBalance | None = None
    initial_balance: WalletBalance | None = None


@dataclass(frozen=True, slots=True)
class WalletCategory:
    id: str
    name: str
    color: str | None = None
    archived: bool = False
    parent_id: str | None = None


@dataclass(frozen=True, slots=True)
class WalletLabel:
    id: str
    name: str
    color: str | None = None
    archived: bool = False


@dataclass(frozen=True, slots=True)
class WalletRecordRule:
    id: str
    name: str | None = None
    keywords: tuple[str, ...] = ()
    category: WalletCatalogRef | None = None
    labels: tuple[WalletCatalogRef, ...] = ()
    from_account_id: str | None = None
    to_account_id: str | None = None


@dataclass(frozen=True, slots=True)
class WalletAmount:
    value: float
    currency_code: str


@dataclass(frozen=True, slots=True)
class WalletRecordTransfer:
    type: str | None = None
    mirror_record: WalletCatalogRef | None = None


@dataclass(frozen=True, slots=True)
class WalletRecord:
    id: str
    account_id: str
    amount: WalletAmount
    record_date: str
    category: WalletCatalogRef | None = None
    counter_party: str | None = None
    labels: tuple[WalletCatalogRef, ...] = ()
    payment_type: str | None = None
    record_type: str | None = None
    record_state: str | None = None
    transfer: WalletRecordTransfer | None = None


# ────────────────────────────────────────────────────────────
# Write-path DTOs — create-record request / batch response
# ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CreateRecordRequest:
    account_id: str
    amount_value: float
    record_date: str
    category_id: str | None = None
    currency_code: str | None = None
    note: str | None = None
    counter_party: str | None = None
    label_ids: tuple[str, ...] = ()
    payment_type: str | None = None
    record_state: str | None = None
    transfer_pairing_mode: str | None = None
    transfer_account_id: str | None = None
    transfer_record_id: str | None = None
    transfer_counter_amount_value: float | None = None
    transfer_counter_amount_currency_code: str | None = None

    def __post_init__(self) -> None:
        if self.amount_value == 0:
            raise ValueError("amount_value must not be zero")
        if self.transfer_pairing_mode is None:
            if any(
                value is not None
                for value in (
                    self.transfer_account_id,
                    self.transfer_record_id,
                    self.transfer_counter_amount_value,
                    self.transfer_counter_amount_currency_code,
                )
            ):
                raise ValueError("transfer fields require transfer_pairing_mode")
            return
        if self.transfer_pairing_mode not in {"new", "existing", "unpaired"}:
            raise ValueError("transfer_pairing_mode must be new, existing, or unpaired")
        if self.transfer_pairing_mode == "new" and not self.transfer_account_id:
            raise ValueError("new transfers require transfer_account_id")
        if self.transfer_pairing_mode == "existing" and not self.transfer_record_id:
            raise ValueError("existing transfers require transfer_record_id")
        if self.transfer_pairing_mode == "unpaired" and (
            self.transfer_account_id or self.transfer_record_id
        ):
            raise ValueError("unpaired transfers cannot name an account or record")
        if self.transfer_counter_amount_value is not None and self.transfer_pairing_mode != "new":
            raise ValueError("counter amount is only supported for new transfers")
        if (self.transfer_counter_amount_value is None) != (
            self.transfer_counter_amount_currency_code is None
        ):
            raise ValueError("counter amount value and currency must be supplied together")

    def as_payload(self) -> dict[str, object]:
        body: dict[str, object] = {
            "accountId": self.account_id,
            "amount": {
                "value": self.amount_value,
            },
            "recordDate": self.record_date,
        }
        if self.category_id is not None:
            body["categoryId"] = self.category_id
        if self.currency_code is not None:
            body["amount"]["currencyCode"] = self.currency_code  # type: ignore[index]
        if self.note is not None:
            body["note"] = self.note
        if self.counter_party is not None:
            body["counterParty"] = self.counter_party
        if self.label_ids:
            body["labelIds"] = list(self.label_ids)
        if self.payment_type is not None:
            body["paymentType"] = self.payment_type
        if self.record_state is not None:
            body["recordState"] = self.record_state
        if self.transfer_pairing_mode is not None:
            transfer: dict[str, object] = {"pairingMode": self.transfer_pairing_mode}
            if self.transfer_account_id is not None:
                transfer["accountId"] = self.transfer_account_id
            if self.transfer_record_id is not None:
                transfer["recordId"] = self.transfer_record_id
            if self.transfer_counter_amount_value is not None:
                transfer["counterAmount"] = {
                    "value": self.transfer_counter_amount_value,
                    "currencyCode": self.transfer_counter_amount_currency_code,
                }
            body["transfer"] = transfer
        return body


@dataclass(frozen=True, slots=True)
class CreateRecordResponseItem:
    index: int
    status: int
    record_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == 200 and self.record_id is not None

    @property
    def is_validation_error(self) -> bool:
        return self.status == 422


@dataclass(frozen=True, slots=True)
class BatchCreateResult:
    items: tuple[CreateRecordResponseItem, ...] = ()

    @property
    def all_succeeded(self) -> bool:
        return all(item.is_success for item in self.items)

    @property
    def succeeded_ids(self) -> tuple[str, ...]:
        return tuple(
            item.record_id
            for item in self.items
            if item.record_id is not None
        )

    @property
    def failed_indices(self) -> tuple[int, ...]:
        return tuple(
            item.index
            for item in self.items
            if not item.is_success
        )


@dataclass(frozen=True, slots=True)
class WalletSubmissionResult:
    status: WalletAttemptStatus
    request: dict[str, object]
    response: dict[str, object] | None
    provider_transaction_id: str | None = None
    error_kind: str | None = None
    error_message: str | None = None
    batch_result: BatchCreateResult | None = None


class MailboxReader(Protocol):
    def fetch_unseen(self, *, limit: int) -> Sequence[MailboxMessage]: ...


class TransactionExtractor(Protocol):
    def extract(self, message: MailboxMessage) -> ExtractionResult: ...


class WalletClient(Protocol):
    def submit(
        self, *, idempotency_key: str, payload: dict[str, object]
    ) -> WalletSubmissionResult: ...

    def get_accounts(self) -> Sequence[WalletAccount]: ...

    def get_categories(self) -> Sequence[WalletCategory]: ...

    def get_labels(self) -> Sequence[WalletLabel]: ...

    def get_record_rules(self) -> Sequence[WalletRecordRule]: ...

    def get_records(self) -> Sequence[WalletRecord]: ...

    def get_records_by_account(
        self, *, account_id: str
    ) -> Sequence[WalletRecord]: ...

    def parse_batch_create_response(
        self, *, raw_response: list[dict[str, object]]
    ) -> BatchCreateResult: ...


@dataclass(frozen=True, slots=True)
class PushMessage:
    """A push message to deliver through the provider."""

    endpoint: str
    keys_p256dh: str
    keys_auth: str
    title: str
    body: str
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PushDeliveryResult:
    """Outcome of delivering one push message."""

    success: bool
    provider_message_id: str | None = None
    error_kind: str | None = None
    error_message: str | None = None
    subscription_stale: bool = False


class PushProvider(Protocol):
    """Deliver a push notification to a browser subscription.

    The contract is stateless: the provider receives a single message and
    returns a result. If the provider reports the subscription as stale,
    callers must disable the subscription.
    """

    def send(self, message: PushMessage) -> PushDeliveryResult: ...

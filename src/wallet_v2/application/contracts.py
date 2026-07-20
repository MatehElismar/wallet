"""Adapter contracts and transport-neutral workflow values."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class WalletSubmissionResult:
    status: WalletAttemptStatus
    request: dict[str, object]
    response: dict[str, object] | None
    provider_transaction_id: str | None = None
    error_kind: str | None = None
    error_message: str | None = None


class MailboxReader(Protocol):
    def fetch_unseen(self, *, limit: int) -> Sequence[MailboxMessage]: ...


class TransactionExtractor(Protocol):
    def extract(self, message: MailboxMessage) -> ExtractionResult: ...


class WalletClient(Protocol):
    def submit(
        self, *, idempotency_key: str, payload: dict[str, object]
    ) -> WalletSubmissionResult: ...

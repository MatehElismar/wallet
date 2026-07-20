"""Wallet V2 domain primitives.

Value objects, enums, and typed identifiers used across the persistence and
(future) workflow layers. This package has no external dependencies beyond the
standard library so it can be imported in any context, including tests.
"""

from wallet_v2.domain.enums import (
    AttemptStatus,
    AuditEventKind,
    CandidateStatus,
    ImportCommandStatus,
    IntegrationMode,
    MailboxSourceStatus,
    ReviewDecision,
    SourceMessageStatus,
    TransactionDirection,
    WalletAttemptStatus,
    WalletReconciliationStatus,
)
from wallet_v2.domain.ids import (
    AttemptId,
    CandidateId,
    ImportCommandId,
    InboxId,
    ReceiptId,
    ReviewTaskId,
    SourceMessageId,
    WalletAttemptId,
    new_attempt_id,
    new_candidate_id,
    new_import_command_id,
    new_inbox_id,
    new_receipt_id,
    new_review_task_id,
    new_source_message_id,
    new_wallet_attempt_id,
)
from wallet_v2.domain.mailbox import (
    CursorEpochMismatch,
    InvalidCursor,
    MailboxCursor,
    MailboxSource,
)
from wallet_v2.domain.money import CurrencyMismatch, InvalidMoney, Money
from wallet_v2.domain.transaction import (
    InvalidTransactionAmount,
    TransactionAmount,
)

__all__ = [
    "AttemptStatus",
    "AuditEventKind",
    "CandidateStatus",
    "ImportCommandStatus",
    "IntegrationMode",
    "MailboxSourceStatus",
    "ReviewDecision",
    "SourceMessageStatus",
    "TransactionDirection",
    "WalletAttemptStatus",
    "WalletReconciliationStatus",
    "AttemptId",
    "CandidateId",
    "ImportCommandId",
    "InboxId",
    "ReceiptId",
    "ReviewTaskId",
    "SourceMessageId",
    "WalletAttemptId",
    "new_attempt_id",
    "new_candidate_id",
    "new_import_command_id",
    "new_inbox_id",
    "new_receipt_id",
    "new_review_task_id",
    "new_source_message_id",
    "new_wallet_attempt_id",
    "CurrencyMismatch",
    "InvalidMoney",
    "Money",
    "InvalidCursor",
    "InvalidMailbox",
    "CursorEpochMismatch",
    "MailboxCursor",
    "MailboxSource",
    "InvalidTransactionAmount",
    "TransactionAmount",
]

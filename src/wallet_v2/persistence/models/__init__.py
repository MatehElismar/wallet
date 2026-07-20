"""Wallet V2 SQLAlchemy 2.0 models.

Importing this package registers every model on the shared
:class:`~wallet_v2.persistence.base.Base.metadata` instance so Alembic
autogeneration and the hand-written migration see the same set of tables.
"""

from wallet_v2.persistence.models.attempt import ProcessingAttempt
from wallet_v2.persistence.models.audit import AuditEvent
from wallet_v2.persistence.models.candidate import TransactionCandidate
from wallet_v2.persistence.models.execution_run import ExecutionRun
from wallet_v2.persistence.models.import_command import ImportCommand
from wallet_v2.persistence.models.inbox import Inbox, InboxCursorHistory
from wallet_v2.persistence.models.review import ReviewDecisionRecord, ReviewTask
from wallet_v2.persistence.models.reconciliation import (
    BankStatement,
    BankStatementLine,
    FinancialAccount,
    FinancialEvent,
    ReconciliationLink,
    StatementReviewBatch,
    TransactionObservation,
)
from wallet_v2.persistence.models.source_message import (
    MessageContentMetadata,
    SourceMessage,
)
from wallet_v2.persistence.models.wallet import WalletAttempt, WalletReceipt

__all__ = [
    "Inbox",
    "InboxCursorHistory",
    "SourceMessage",
    "MessageContentMetadata",
    "ProcessingAttempt",
    "TransactionCandidate",
    "ExecutionRun",
    "ReviewTask",
    "ReviewDecisionRecord",
    "ImportCommand",
    "WalletAttempt",
    "WalletReceipt",
    "AuditEvent",
    "FinancialAccount",
    "BankStatement",
    "BankStatementLine",
    "TransactionObservation",
    "ReconciliationLink",
    "StatementReviewBatch",
    "FinancialEvent",
]

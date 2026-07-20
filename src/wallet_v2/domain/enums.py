"""Workflow state enums for the Wallet V2 pipeline.

Every enum is string-based so its value is stable across migrations, audit
logs, and serialized JSON columns. New members must be appended; never reorder
or rename existing members.
"""

from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    """String enum base with a stable value convention.

    A local base is used instead of ``enum.StrEnum`` so the project remains
    explicit about value stability and to support Python 3.12 without
    depending on ``StrEnum``'s ``__format__`` semantics.
    """

    def __str__(self) -> str:
        return self.value


class IntegrationMode(_StrEnum):
    """Operating mode for an integration (mailbox, LLM, Wallet).

    Each integration (mailbox, LLM, Wallet) is configured with one of three
    modes instead of a boolean enable flag. The mode controls whether an
    adapter is available to a run. The execution-run mode determines whether
    a Wallet import is recorded as intent or submitted to the provider.

    - ``disabled`` : integration is off; no credentials required, no calls made
    - ``dry_run``  : configured for a dry-run execution
    - ``live``     : configured for a live execution

    Modes are append-only: never reorder or rename existing members. New
    members must be added at the end and given a stable, lowercase string
    value.
    """

    DISABLED = "disabled"
    DRY_RUN = "dry_run"
    LIVE = "live"


class MailboxSourceStatus(_StrEnum):
    """Lifecycle of a configured mailbox source.

    A source is the durable identity of a mailbox account/folder. Transitions:

    - ``active`` -> ``paused`` (operator halts ingestion)
    - ``paused``  -> ``active`` (operator resumes ingestion)
    - ``active``  -> ``drained`` (no further messages expected)
    - ``active``  -> ``revoked`` (credentials revoked by the provider)
    """

    ACTIVE = "active"
    PAUSED = "paused"
    DRAINED = "drained"
    REVOKED = "revoked"


class SourceMessageStatus(_StrEnum):
    """Lifecycle of a raw source message (e.g. an email)."""

    RECEIVED = "received"
    CONSUMED = "consumed"
    ARCHIVED = "archived"
    QUARANTINED = "quarantined"


class AttemptStatus(_StrEnum):
    """Outcome of a single processing attempt against a source message.

    Attempt records are immutable and append-only: a failed attempt is
    never mutated to ``SUCCEEDED``. A new attempt is issued instead.

    ``invalid_output`` and ``schema_violation`` are terminal failure states
    distinguished from generic ``failed`` for forensic clarity: an
    ``invalid_output`` attempt produced unparseable content, while a
    ``schema_violation`` attempt produced parseable content that violated
    the candidate schema. A replay is always a new attempt row, never a
    mutation of an existing one.

    There is no ``SUPERSEDED`` state. Old attempts are never back-patched;
    a replay simply inserts a new row with a higher ``attempt_index``.
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALID_OUTPUT = "invalid_output"
    SCHEMA_VIOLATION = "schema_violation"


class CandidateStatus(_StrEnum):
    """Lifecycle of a transaction candidate produced by an attempt."""

    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPORTED = "imported"
    DROPPED = "dropped"


class DocumentKind(_StrEnum):
    """Financial-document role assigned by extraction."""

    NOTIFICATION = "notification"
    STATEMENT = "statement"


class ObservationStatus(_StrEnum):
    """Lifecycle of an event observed outside an authoritative statement."""

    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class StatementStatus(_StrEnum):
    """Lifecycle of a bank statement document version."""

    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReconciliationOutcome(_StrEnum):
    """Current resolution of a statement line against prior evidence."""

    NEW = "new"
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    IGNORED = "ignored"


class ReconciliationMethod(_StrEnum):
    """How a statement-line resolution was made."""

    EXACT_REFERENCE = "exact_reference"
    EXACT_DETAILS = "exact_details"
    MANUAL = "manual"
    NONE = "none"


class FinancialEventStatus(_StrEnum):
    """Lifecycle of a canonical, statement-confirmed financial event."""

    POSTED = "posted"
    REVERSED = "reversed"
    CANCELLED = "cancelled"


class ReviewDecision(_StrEnum):
    """A human reviewer's decision on a candidate.

    ``approved`` and ``rejected`` are terminal for that candidate. ``deferred``
    is non-terminal and signals that the candidate will be superseded by a new
    one produced from a fresh attempt.
    """

    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ImportCommandStatus(_StrEnum):
    """Lifecycle of an import command issued from an approved candidate.

    Commands are immutable once issued; state transitions only progress
    forward through a strictly monotonic state machine:

    - ``queued``   -> ``in_flight``   (worker picked up the command)
    - ``in_flight`` -> ``succeeded`` | ``failed`` | ``unknown``
    - ``unknown``  -> ``succeeded`` | ``failed`` (resolved by reconciliation)
    - ``succeeded`` -> ``reconciled`` (receipt matched)
    - ``failed``    -> ``reconciled``  (terminal reconciliation note)

    ``unknown`` is the post-timeout state where the Wallet provider may have
    applied the transaction but the response was lost. Resolving it requires
    an out-of-band reconciliation query, not a blind retry.
    """

    QUEUED = "queued"
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RECONCILED = "reconciled"


class WalletAttemptStatus(_StrEnum):
    """Outcome of a single submission to the Wallet provider.

    Like processing attempts, Wallet attempts are immutable: a failed
    submission is recorded as ``FAILED`` and a new attempt is issued. The
    ``unknown`` variant mirrors :class:`ImportCommandStatus.UNKNOWN` and is
    resolved only by a Wallet receipt or a reconciliation decision.
    """

    PENDING = "pending"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RECONCILED = "reconciled"


class WalletReconciliationStatus(_StrEnum):
    """Outcome of reconciling a Wallet receipt against its import command."""

    MATCHED = "matched"
    MISMATCH = "mismatch"
    PENDING = "pending"


class TransactionDirection(_StrEnum):
    """Direction of a transaction candidate relative to the wallet.

    Both directions carry a non-negative magnitude in ``Money``; the sign is
    determined by this enum, not by the amount.
    """

    DEBIT = "debit"
    CREDIT = "credit"


class AuditEventKind(_StrEnum):
    """Categorizes an :class:`AuditEvent` row for filtering and retention."""

    SOURCE_MESSAGE_RECEIVED = "source_message_received"
    ATTEMPT_CREATED = "attempt_created"
    CANDIDATE_PROPOSED = "candidate_proposed"
    REVIEW_DECISION = "review_decision"
    IMPORT_COMMAND_ISSUED = "import_command_issued"
    IMPORT_COMMAND_TRANSITION = "import_command_transition"
    WALLET_ATTEMPT = "wallet_attempt"
    WALLET_RECEIPT = "wallet_receipt"
    RECONCILIATION = "reconciliation"
    RETENTION_PURGE = "retention_purge"
    EXECUTION_RUN_STARTED = "execution_run_started"
    EXECUTION_RUN_FINISHED = "execution_run_finished"
    STATEMENT_INGESTED = "statement_ingested"
    STATEMENT_BATCH_DECIDED = "statement_batch_decided"
    RECONCILIATION_RESOLVED = "reconciliation_resolved"
    FINANCIAL_ACCOUNT_MAPPED = "financial_account_mapped"

"""Statement reconciliation aggregates.

Notifications are evidence of an observed transaction. A periodic statement
is a bank-issued account document, so it is stored with its own line items,
matching decisions, and review batch before it can create canonical events.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.domain.enums import (
    FinancialEventStatus,
    ObservationStatus,
    ReconciliationMethod,
    ReconciliationOutcome,
    StatementStatus,
    TransactionDirection,
)
from wallet_v2.persistence.base import Base, Immutable, Timestamped

if TYPE_CHECKING:
    from wallet_v2.persistence.models.attempt import ProcessingAttempt
    from wallet_v2.persistence.models.candidate import TransactionCandidate
    from wallet_v2.persistence.models.import_command import ImportCommand
    from wallet_v2.persistence.models.source_message import SourceMessage


class FinancialAccount(Base, Timestamped):
    """A bank/card account identity, optionally mapped to a Wallet account."""

    __tablename__ = "financial_accounts"
    __table_args__ = (
        UniqueConstraint(
            "issuer", "external_reference",
            name="uq_financial_accounts_issuer_external",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    issuer: Mapped[str] = mapped_column(String(128), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    wallet_account_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    statements: Mapped[list["BankStatement"]] = relationship(back_populates="account")
    events: Mapped[list["FinancialEvent"]] = relationship(back_populates="account")
    observations: Mapped[list["TransactionObservation"]] = relationship(
        back_populates="account"
    )


class BankStatement(Base, Timestamped):
    """One extracted version of a bank-issued periodic statement."""

    __tablename__ = "bank_statements"
    __table_args__ = (
        UniqueConstraint(
            "source_message_id", "statement_version",
            name="uq_statements_source_version",
        ),
        UniqueConstraint(
            "account_id", "document_fingerprint",
            name="uq_statements_account_document_fingerprint",
        ),
        CheckConstraint("statement_version >= 1", name="ck_statements_version_positive"),
        CheckConstraint(
            "status IN ('open', 'approved', 'rejected', 'superseded')",
            name="ck_statements_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="RESTRICT"), nullable=False
    )
    processing_attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    statement_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[StatementStatus] = mapped_column(
        String(16), nullable=False, default=StatementStatus.OPEN
    )
    document_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    statement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    opening_balance_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    closing_balance_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source_message: Mapped["SourceMessage"] = relationship(back_populates="statements")
    processing_attempt: Mapped["ProcessingAttempt"] = relationship(back_populates="statements")
    account: Mapped["FinancialAccount"] = relationship(back_populates="statements")
    lines: Mapped[list["BankStatementLine"]] = relationship(
        back_populates="statement",
        cascade="save-update, merge",
        order_by="BankStatementLine.line_index",
    )
    review_batch: Mapped["StatementReviewBatch | None"] = relationship(
        back_populates="statement", uselist=False
    )


class BankStatementLine(Base, Immutable):
    """An immutable posted line item from a statement document."""

    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        UniqueConstraint(
            "statement_id", "line_index", name="uq_statement_lines_statement_index"
        ),
        CheckConstraint("line_index >= 1", name="ck_statement_lines_index_positive"),
        CheckConstraint("amount_minor > 0", name="ck_statement_lines_amount_positive"),
        CheckConstraint(
            "event_status IN ('posted', 'reversed', 'cancelled')",
            name="ck_statement_lines_event_status",
        ),
        CheckConstraint(
            "length(currency) = 3 "
            "AND substr(currency, 1, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(currency, 2, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(currency, 3, 1) BETWEEN 'A' AND 'Z'",
            name="ck_statement_lines_currency_format",
        ),
        Index("ix_statement_lines_fingerprint", "line_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    statement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="RESTRICT"), nullable=False
    )
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[TransactionDirection] = mapped_column(String(16), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    posting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    running_balance_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_status: Mapped[FinancialEventStatus] = mapped_column(
        String(16), nullable=False, default=FinancialEventStatus.POSTED
    )
    related_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    statement: Mapped["BankStatement"] = relationship(back_populates="lines")
    resolution: Mapped["ReconciliationLink | None"] = relationship(
        back_populates="statement_line", uselist=False
    )
    event: Mapped["FinancialEvent | None"] = relationship(
        back_populates="statement_line", uselist=False
    )


class TransactionObservation(Base, Immutable):
    """A notification-derived observation that may later be confirmed by a statement."""

    __tablename__ = "transaction_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_message_id", "source_item_index", "observation_version",
            name="uq_observations_source_item_version",
        ),
        UniqueConstraint("candidate_id", name="uq_observations_candidate_one"),
        CheckConstraint("observation_version >= 1", name="ck_observations_version_positive"),
        CheckConstraint("source_item_index >= 1", name="ck_observations_index_positive"),
        CheckConstraint("amount_minor > 0", name="ck_observations_amount_positive"),
        CheckConstraint(
            "status IN ('provisional', 'confirmed', 'rejected', 'superseded')",
            name="ck_observations_status",
        ),
        Index(
            "ix_observations_match",
            "amount_minor", "currency", "direction", "transaction_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="RESTRICT"), nullable=False
    )
    processing_attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transaction_candidates.id", ondelete="RESTRICT"), nullable=False
    )
    source_item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ObservationStatus] = mapped_column(
        String(16), nullable=False, default=ObservationStatus.PROVISIONAL
    )
    direction: Mapped[TransactionDirection] = mapped_column(String(16), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    source_message: Mapped["SourceMessage"] = relationship(back_populates="observations")
    processing_attempt: Mapped["ProcessingAttempt"] = relationship(back_populates="observations")
    account: Mapped["FinancialAccount | None"] = relationship(back_populates="observations")
    candidate: Mapped["TransactionCandidate"] = relationship(
        back_populates="observation", uselist=False
    )
    resolution: Mapped["ReconciliationLink | None"] = relationship(
        back_populates="observation", uselist=False
    )


class ReconciliationLink(Base, Timestamped):
    """The current resolution for one statement line, with audit events on edits."""

    __tablename__ = "reconciliation_links"
    __table_args__ = (
        UniqueConstraint("statement_line_id", name="uq_reconciliation_line_one"),
        UniqueConstraint("observation_id", name="uq_reconciliation_observation_one"),
        CheckConstraint(
            "outcome IN ('new', 'matched', 'ambiguous', 'ignored')",
            name="ck_reconciliation_outcome",
        ),
        CheckConstraint(
            "method IN ('exact_reference', 'exact_details', 'manual', 'none')",
            name="ck_reconciliation_method",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    statement_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statement_lines.id", ondelete="RESTRICT"), nullable=False
    )
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transaction_observations.id", ondelete="RESTRICT"), nullable=True
    )
    outcome: Mapped[ReconciliationOutcome] = mapped_column(String(16), nullable=False)
    method: Mapped[ReconciliationMethod] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    statement_line: Mapped["BankStatementLine"] = relationship(back_populates="resolution")
    observation: Mapped["TransactionObservation | None"] = relationship(back_populates="resolution")


class StatementReviewBatch(Base, Timestamped):
    """The all-at-once reviewer decision boundary for a statement."""

    __tablename__ = "statement_review_batches"
    __table_args__ = (
        UniqueConstraint(
            "statement_id", name="uq_statement_review_batches_statement_one"
        ),
        CheckConstraint(
            "state IN ('open', 'approved', 'rejected', 'superseded')",
            name="ck_statement_review_batches_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    statement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    reviewer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    statement: Mapped["BankStatement"] = relationship(
        back_populates="review_batch", uselist=False
    )


class FinancialEvent(Base, Immutable):
    """A canonical posted event created only by an approved statement batch."""

    __tablename__ = "financial_events"
    __table_args__ = (
        UniqueConstraint(
            "statement_line_id", name="uq_financial_events_statement_line_one"
        ),
        CheckConstraint(
            "status IN ('posted', 'reversed', 'cancelled')",
            name="ck_financial_events_status",
        ),
        CheckConstraint("amount_minor > 0", name="ck_financial_events_amount_positive"),
        Index("ix_financial_events_account_posting", "account_id", "posting_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    statement_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statement_lines.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[FinancialEventStatus] = mapped_column(
        String(16), nullable=False, default=FinancialEventStatus.POSTED
    )
    direction: Mapped[TransactionDirection] = mapped_column(String(16), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    posting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reverses_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("financial_events.id", ondelete="RESTRICT"), nullable=True
    )

    account: Mapped["FinancialAccount"] = relationship(back_populates="events")
    statement_line: Mapped["BankStatementLine"] = relationship(
        back_populates="event", uselist=False
    )
    reverses_event: Mapped["FinancialEvent | None"] = relationship(
        remote_side="FinancialEvent.id", foreign_keys=[reverses_event_id]
    )
    import_command: Mapped["ImportCommand | None"] = relationship(
        back_populates="financial_event", uselist=False
    )

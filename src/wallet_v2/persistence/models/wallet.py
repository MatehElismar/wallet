"""Wallet attempts and receipts.

Two tables close the workflow:

* :class:`WalletAttempt` — an immutable record of one submission to the
  Wallet provider. Multiple attempts may exist per import command (retry
  after failure or after an ``unknown`` outcome); each is its own
  immutable row. Mirrors :class:`ImportCommandStatus.UNKNOWN` via
  :attr:`WalletAttemptStatus.UNKNOWN`.
* :class:`WalletReceipt` — the provider's confirmation, 1:1 with the
  import command. Nullable until the provider acknowledges or a
  reconciliation job resolves an ``unknown`` command. Carries the
  confirmed amount/currency so reconciliation can compare against the
  candidate.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.domain.enums import WalletAttemptStatus, WalletReconciliationStatus
from wallet_v2.persistence.base import Base, Immutable, Timestamped
from wallet_v2.persistence.types import JSONB

if TYPE_CHECKING:
    from wallet_v2.persistence.models.import_command import ImportCommand


class WalletAttempt(Base, Immutable):
    """An immutable record of one Wallet API submission.

    ``attempt_index`` is 1-based and unique per ``import_command_id`` so
    the submission history is strictly ordered. ``status`` uses
    :class:`WalletAttemptStatus`, which includes ``unknown`` for the
    post-timeout hold state.
    """

    __tablename__ = "wallet_attempts"
    __table_args__ = (
        UniqueConstraint(
            "import_command_id",
            "attempt_index",
            name="uq_wallet_attempts_command_index",
        ),
        CheckConstraint("attempt_index >= 1", name="ck_wallet_attempts_index"),
        CheckConstraint(
            "status IN ('pending', 'submitted', 'acknowledged', "
            "'failed', 'unknown', 'reconciled')",
            name="ck_wallet_attempts_status",
        ),
        Index(
            "ix_wallet_attempts_command_status",
            "import_command_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    import_command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_commands.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[WalletAttemptStatus] = mapped_column(
        String(16), nullable=False, default=WalletAttemptStatus.PENDING
    )
    provider_request: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    provider_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    import_command: Mapped["ImportCommand"] = relationship(
        back_populates="wallet_attempts"
    )
    receipt: Mapped["WalletReceipt | None"] = relationship(
        back_populates="wallet_attempt",
        cascade="save-update, merge",
        uselist=False,
    )


class WalletReceipt(Base, Timestamped):
    """A Wallet provider receipt, 1:1 with an :class:`ImportCommand`.

    A receipt exists only after the provider has confirmed the transaction
    (or after a reconciliation job has resolved an ``unknown`` command).
    The unique constraint on ``import_command_id`` enforces at most one
    receipt per command.

    ``confirmed_amount_minor`` and ``confirmed_currency`` allow
    reconciliation to compare the provider's confirmed amount against the
    candidate's amount and flag mismatches.
    """

    __tablename__ = "wallet_receipts"
    __table_args__ = (
        UniqueConstraint(
            "import_command_id", name="uq_wallet_receipts_command_one"
        ),
        CheckConstraint(
            "confirmed_amount_minor IS NULL OR confirmed_amount_minor >= 0",
            name="ck_wallet_receipts_amount_nonnegative",
        ),
        CheckConstraint(
            "confirmed_currency IS NULL OR "
            "(length(confirmed_currency) = 3 "
            "AND substr(confirmed_currency, 1, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(confirmed_currency, 2, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(confirmed_currency, 3, 1) BETWEEN 'A' AND 'Z')",
            name="ck_wallet_receipts_currency_format",
        ),
        CheckConstraint(
            "reconciliation_status IN ('matched', 'mismatch', 'pending')",
            name="ck_wallet_receipts_reconciliation_status",
        ),
        Index(
            "ix_wallet_receipts_reconciliation_status",
            "reconciliation_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    import_command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_commands.id", ondelete="RESTRICT"),
        nullable=False,
    )
    wallet_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wallet_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    reconciliation_status: Mapped[WalletReconciliationStatus] = mapped_column(
        String(16),
        nullable=False,
        default=WalletReconciliationStatus.PENDING,
    )
    confirmed_amount_minor: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    confirmed_currency: Mapped[str | None] = mapped_column(
        String(3), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    import_command: Mapped["ImportCommand"] = relationship(
        back_populates="receipt"
    )
    wallet_attempt: Mapped["WalletAttempt | None"] = relationship(
        back_populates="receipt"
    )

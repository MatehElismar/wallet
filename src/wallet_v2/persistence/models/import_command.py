"""Import commands issued from approved canonical financial events.

An :class:`ImportCommand` is the durable record of an instruction to the
Wallet provider to apply one transaction. New commands are created only from
an approved statement-backed financial event (the nullable candidate origin is
retained for legacy records) and carry a deterministic, unique idempotency key so
that retries against the Wallet provider are exactly-once from the
provider's perspective.

State machine (DeepSeek V4 review, section 5):

    queued -> in_flight -> succeeded | failed | unknown
    unknown -> succeeded | failed      (resolved by reconciliation)
    succeeded -> reconciled             (receipt matched)
    failed    -> reconciled             (terminal reconciliation note)

``unknown`` is the post-timeout hold state: the Wallet provider may have
applied the transaction but the response was lost. Resolving it requires
an out-of-band reconciliation query — never a blind retry.

This table is **mutable** (it carries ``updated_at``): the ``status``
column records the current state of the command and advances as the
worker transitions it through the state machine. The full transition
history is recorded in :class:`AuditEvent` rows; the command row itself
only ever reflects the *current* state.

Immutability invariants that *do* hold for the command:

* Exactly one immutable origin is present: a legacy ``candidate_id`` or a
  canonical ``financial_event_id``.
* ``idempotency_key`` is unique and deterministic (one key per logical
  transaction; the Wallet provider must deduplicate on it).
* ``payload`` is immutable after insert in practice: the application
  layer must never rewrite it. The schema does not enforce payload
  immutability at the database level — that is an application invariant
  documented here and covered by audit events.
* ``issued_at`` is the timestamp at which the command was issued; it is
  immutable in practice (set once at insert).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from wallet_v2.persistence.types import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.domain.enums import ImportCommandStatus
from wallet_v2.persistence.base import Base, Timestamped

if TYPE_CHECKING:
    from wallet_v2.persistence.models.candidate import TransactionCandidate
    from wallet_v2.persistence.models.reconciliation import FinancialEvent
    from wallet_v2.persistence.models.wallet import WalletAttempt, WalletReceipt


class ImportCommand(Base, Timestamped):
    """An import command issued from an approved canonical financial event.

    ``status`` is mutable and advances through the state machine. The
    ``payload``, ``candidate_id``, ``idempotency_key``, and ``issued_at``
    fields are immutable in practice; the application layer must never
    rewrite them, and an :class:`AuditEvent` row is emitted on every
    status transition so the history is reconstructable even if the
    command row is later mutated.

    Attributes:
        id: UUID primary key.
        candidate_id: legacy 1:1 FK retained for historical commands.
        financial_event_id: 1:1 FK to the approved canonical statement event.
        idempotency_key: deterministic, unique key derived from the origin's
            immutable fields. The Wallet provider must honour
            it for exactly-once semantics.
        status: the current state in the ``queued -> in_flight ->
            succeeded | failed | unknown -> reconciled`` machine.
        payload: the JSONB payload sent to the Wallet provider (amount,
            currency, direction, merchant, reference, etc.).
        issued_at: when the command was issued. Immutable in practice.
        created_at: row insertion timestamp.
        updated_at: last mutation timestamp; refreshed on every UPDATE
            of ``status``.
    """

    __tablename__ = "import_commands"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", name="uq_import_commands_candidate_one"
        ),
        UniqueConstraint(
            "financial_event_id", name="uq_import_commands_financial_event_one"
        ),
        UniqueConstraint(
            "idempotency_key", name="uq_import_commands_idempotency_key"
        ),
        CheckConstraint(
            "status IN ('queued', 'in_flight', 'succeeded', "
            "'failed', 'unknown', 'reconciled')",
            name="ck_import_commands_status",
        ),
        CheckConstraint(
            "(candidate_id IS NOT NULL AND financial_event_id IS NULL) "
            "OR (candidate_id IS NULL AND financial_event_id IS NOT NULL)",
            name="ck_import_commands_one_origin",
        ),
        CheckConstraint(
            "length(idempotency_key) >= 16",
            name="ck_import_commands_idempotency_key_len",
        ),
        Index("ix_import_commands_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_runs.id", ondelete="RESTRICT"), nullable=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transaction_candidates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    financial_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("financial_events.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    status: Mapped[ImportCommandStatus] = mapped_column(
        String(16),
        nullable=False,
        default=ImportCommandStatus.QUEUED,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    candidate: Mapped["TransactionCandidate | None"] = relationship(
        back_populates="import_command", uselist=False
    )
    financial_event: Mapped["FinancialEvent | None"] = relationship(
        back_populates="import_command", uselist=False
    )
    wallet_attempts: Mapped[list["WalletAttempt"]] = relationship(
        back_populates="import_command",
        cascade="save-update, merge",
        order_by="WalletAttempt.attempt_index",
    )
    receipt: Mapped["WalletReceipt | None"] = relationship(
        back_populates="import_command",
        cascade="save-update, merge",
        uselist=False,
    )

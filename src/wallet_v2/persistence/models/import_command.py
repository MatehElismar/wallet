"""Import commands issued from approved candidates.

An :class:`ImportCommand` is the durable record of an instruction to the
Wallet provider to apply one transaction. It is created only from an
approved candidate and carries a deterministic, unique idempotency key so
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

* ``candidate_id`` is unique (one command per approved candidate).
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
    from wallet_v2.persistence.models.wallet import WalletAttempt, WalletReceipt


class ImportCommand(Base, Timestamped):
    """An import command issued from an approved candidate.

    ``status`` is mutable and advances through the state machine. The
    ``payload``, ``candidate_id``, ``idempotency_key``, and ``issued_at``
    fields are immutable in practice; the application layer must never
    rewrite them, and an :class:`AuditEvent` row is emitted on every
    status transition so the history is reconstructable even if the
    command row is later mutated.

    Attributes:
        id: UUID primary key.
        candidate_id: 1:1 FK to the approved candidate. Unique, so a
            candidate can spawn at most one import command.
        idempotency_key: deterministic, unique key derived from the
            candidate's immutable fields. The Wallet provider must honour
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
            "idempotency_key", name="uq_import_commands_idempotency_key"
        ),
        CheckConstraint(
            "status IN ('queued', 'in_flight', 'succeeded', "
            "'failed', 'unknown', 'reconciled')",
            name="ck_import_commands_status",
        ),
        CheckConstraint(
            "length(idempotency_key) >= 16",
            name="ck_import_commands_idempotency_key_len",
        ),
        Index("ix_import_commands_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transaction_candidates.id", ondelete="RESTRICT"),
        nullable=False,
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

    candidate: Mapped["TransactionCandidate"] = relationship(
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

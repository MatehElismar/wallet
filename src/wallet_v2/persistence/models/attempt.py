"""Immutable processing attempts.

A :class:`ProcessingAttempt` is one LLM invocation against a source message
(parse / extract). The DeepSeek V4 review (section 3) recommended this grain
because it preserves forensic value: each attempt carries the raw prompt
response, structured output, model metadata, and terminal status.

Invariants enforced by the schema:

* **Append-only.** This table uses :class:`Immutable` (no ``updated_at``).
* **Idempotency.** ``idempotency_key`` is unique; a crashed retry that
  re-issues the same key loses the race with a unique constraint violation
  rather than creating a duplicate.
* **Per-source-message ordering.** ``(source_message_id, attempt_index)`` is
  unique so the attempt history is strictly ordered and complete for any
  message.
* **PII retention.** ``raw_response`` is JSONB and carries the raw LLM
  output; it has its own ``retain_until`` / ``purged_at`` columns because it
  may contain email body fragments.
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

from wallet_v2.domain.enums import AttemptStatus
from wallet_v2.persistence.base import Base, Immutable
from wallet_v2.persistence.types import JSONB

if TYPE_CHECKING:
    from wallet_v2.persistence.models.candidate import TransactionCandidate
    from wallet_v2.persistence.models.source_message import SourceMessage


class ProcessingAttempt(Base, Immutable):
    """One LLM extraction attempt against a :class:`SourceMessage`.

    Terminal states are :attr:`AttemptStatus.SUCCEEDED`,
    :attr:`AttemptStatus.FAILED`,
    :attr:`AttemptStatus.INVALID_OUTPUT`,
    :attr:`AttemptStatus.SCHEMA_VIOLATION`. There is no ``SUPERSEDED``
    state: old attempts are never back-patched. A replay of the same
    source message produces a new attempt row with a higher
    ``attempt_index``; the prior attempt remains in its terminal state
    for audit.
    """

    __tablename__ = "processing_attempts"
    __table_args__ = (
        UniqueConstraint(
            "source_message_id",
            "attempt_index",
            name="uq_attempts_source_message_index",
        ),
        UniqueConstraint(
            "idempotency_key", name="uq_attempts_idempotency_key"
        ),
        CheckConstraint(
            "attempt_index >= 1", name="ck_attempts_index_positive"
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', "
            "'invalid_output', 'schema_violation')",
            name="ck_attempts_status",
        ),
        Index(
            "ix_processing_attempts_source_message_status",
            "source_message_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    status: Mapped[AttemptStatus] = mapped_column(
        String(32), nullable=False, default=AttemptStatus.PENDING
    )
    model_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    model_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    structured_output: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    error_kind: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    retain_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source_message: Mapped["SourceMessage"] = relationship(
        back_populates="attempts"
    )
    candidates: Mapped[list["TransactionCandidate"]] = relationship(
        back_populates="attempt"
    )

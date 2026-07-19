"""Transaction candidates derived from successful attempts.

A :class:`TransactionCandidate` is the structured representation of a
financial transaction extracted from a source message. It carries the
immutable merchant/amount/currency fields plus a candidate-version number
so that rejections and re-processing produce a new row rather than a
mutation of the old one.

Per the DeepSeek V4 review (section 2), monetary amounts are stored as a
pair of columns: ``amount_minor`` (BIGINT, integer minor units — never
float or Decimal) and ``currency`` (CHAR(3) ISO 4217). The sign is encoded
by :class:`TransactionDirection`, not by the amount. The strictly-positive
invariant on transaction magnitude is enforced **at the database level**
by a ``CHECK (amount_minor > 0)`` constraint, in addition to the
application-layer :class:`~wallet_v2.domain.transaction.TransactionAmount`
guard.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.domain.enums import CandidateStatus, TransactionDirection
from wallet_v2.persistence.base import Base, Timestamped
from wallet_v2.persistence.types import JSONB

if TYPE_CHECKING:
    from wallet_v2.persistence.models.attempt import ProcessingAttempt
    from wallet_v2.persistence.models.import_command import ImportCommand
    from wallet_v2.persistence.models.review import ReviewTask
    from wallet_v2.persistence.models.source_message import SourceMessage


class TransactionCandidate(Base, Timestamped):
    """A transaction candidate produced by a successful processing attempt.

    ``previous_candidate_id`` is a self-reference supporting the version
    chain called out in the DeepSeek review (section 4): if a reviewer
    defers, a fresh attempt produces a new candidate whose
    ``previous_candidate_id`` points at the deferred one. Old candidates
    remain immutable for audit.
    """

    __tablename__ = "transaction_candidates"
    __table_args__ = (
        UniqueConstraint(
            "source_message_id",
            "candidate_version",
            name="uq_candidates_source_message_version",
        ),
        CheckConstraint(
            "amount_minor > 0",
            name="ck_candidates_amount_positive",
        ),
        CheckConstraint(
            "length(currency) = 3 "
            "AND substr(currency, 1, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(currency, 2, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(currency, 3, 1) BETWEEN 'A' AND 'Z'",
            name="ck_candidates_currency_format",
        ),
        CheckConstraint(
            "candidate_version >= 1",
            name="ck_candidates_version_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_attempts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_version: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    previous_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transaction_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[CandidateStatus] = mapped_column(
        String(32), nullable=False, default=CandidateStatus.PROPOSED
    )
    direction: Mapped[TransactionDirection] = mapped_column(
        String(16), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    transaction_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    structured_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )

    source_message: Mapped["SourceMessage"] = relationship(
        back_populates="candidates"
    )
    attempt: Mapped["ProcessingAttempt"] = relationship(
        back_populates="candidates"
    )
    previous_candidate: Mapped["TransactionCandidate | None"] = relationship(
        remote_side="TransactionCandidate.id", foreign_keys=[previous_candidate_id]
    )
    review_task: Mapped["ReviewTask | None"] = relationship(
        back_populates="candidate", uselist=False
    )
    import_command: Mapped["ImportCommand | None"] = relationship(
        back_populates="candidate", uselist=False
    )

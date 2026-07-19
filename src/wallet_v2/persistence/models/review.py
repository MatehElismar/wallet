"""Review tasks and immutable review decisions.

The DeepSeek V4 review (section 4) called out review policy as underspecified:
reviewer identity, decision types, timestamps, and an evidence FK chain must
all be modelled. Two tables materialize that here:

* :class:`ReviewTask` — a 1:1 work item for the candidate currently under
  review. Mutable (``Timestamped``) because its ``state`` transitions
  ``open -> decided | superseded`` as the review progresses.
* :class:`ReviewDecisionRecord` — an immutable, append-only row recording
  one reviewer's decision at a point in time. A single review task may
  accumulate multiple decision rows (e.g. ``deferred`` then ``approved``
  after re-processing); each row is individually immutable. The latest
  decision by ``decided_at`` is the current decision.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.domain.enums import ReviewDecision
from wallet_v2.persistence.base import Base, Immutable, Timestamped

if TYPE_CHECKING:
    from wallet_v2.persistence.models.candidate import TransactionCandidate


class ReviewTask(Base, Timestamped):
    """A review work item, 1:1 with the candidate under review.

    ``state`` is the only mutable field:

    - ``open``      — awaiting a decision.
    - ``decided``   — a terminal decision (approved / rejected) was recorded.
    - ``superseded``— the candidate was deferred and a new candidate+task
      pair was created; this task is no longer active.
    """

    __tablename__ = "review_tasks"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", name="uq_review_tasks_candidate_one"
        ),
        CheckConstraint(
            "state IN ('open', 'decided', 'superseded')",
            name="ck_review_tasks_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transaction_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open"
    )

    candidate: Mapped["TransactionCandidate"] = relationship(
        back_populates="review_task", uselist=False
    )
    decisions: Mapped[list["ReviewDecisionRecord"]] = relationship(
        back_populates="review_task",
        cascade="save-update, merge",
        order_by="ReviewDecisionRecord.decided_at",
    )


class ReviewDecisionRecord(Base, Immutable):
    """An immutable reviewer decision on a candidate.

    A reviewer may issue multiple decision rows over the lifecycle of a
    review task (e.g. ``deferred`` then ``approved``), but each row is
    individually immutable. The CHECK constraint on ``decision`` ensures
    only the three sanctioned values from
    :class:`~wallet_v2.domain.enums.ReviewDecision` are accepted.
    """

    __tablename__ = "review_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'rejected', 'deferred')",
            name="ck_review_decisions_decision",
        ),
        Index(
            "ix_review_decisions_task_decided",
            "review_task_id",
            "decided_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transaction_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[ReviewDecision] = mapped_column(
        String(16), nullable=False
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    review_task: Mapped[ReviewTask] = relationship(back_populates="decisions")

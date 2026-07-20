"""Source messages and their parsed content metadata.

The DeepSeek V4 review (section 6) recommended defaulting to *hash-only*
storage for raw emails: store a salted content hash and structured metadata
(sender, subject, message-id header, sent_at) rather than the full MIME
body. That keeps PII out of the database by default; a future encrypted
PII store can be added separately if raw retention is ever required.

Two tables:

* :class:`SourceMessage` — the durable, deduplicated record of a fetched
  message. Unique on ``(inbox_id, uid_validity, message_uid)`` so a
  UIDVALIDITY reset or a refetch cannot create a duplicate.
* :class:`MessageContentMetadata` — 1:1 parsed headers. Split out so the
  PII-carrying fields can have a different retention policy from the
  deduplication record on :class:`SourceMessage`.
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
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.domain.enums import SourceMessageStatus
from wallet_v2.persistence.base import Base, Timestamped

if TYPE_CHECKING:
    from wallet_v2.persistence.models.attempt import ProcessingAttempt
    from wallet_v2.persistence.models.inbox import Inbox
    from wallet_v2.persistence.models.candidate import TransactionCandidate
    from wallet_v2.persistence.models.reconciliation import (
        BankStatement,
        TransactionObservation,
    )


class SourceMessage(Base, Timestamped):
    """A fetched source message, identified by its IMAP coordinates.

    The composite unique constraint ``(inbox_id, uid_validity, message_uid)``
    is the primary replay guard: a UIDVALIDITY reset produces a new epoch
    with its own UID sequence, so stale messages from the prior epoch cannot
    collide with the new one.
    """

    __tablename__ = "source_messages"
    __table_args__ = (
        UniqueConstraint(
            "inbox_id",
            "uid_validity",
            "message_uid",
            name="uq_source_messages_inbox_uidvalidity_uid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    execution_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_runs.id", ondelete="RESTRICT"), nullable=True
    )
    inbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inboxes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    uid_validity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[SourceMessageStatus] = mapped_column(
        String(16),
        nullable=False,
        default=SourceMessageStatus.RECEIVED,
    )
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    retain_until: Mapped[datetime | None] = mapped_column(nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(nullable=True)

    inbox: Mapped["Inbox"] = relationship(back_populates="source_messages")
    content_metadata: Mapped["MessageContentMetadata | None"] = relationship(
        back_populates="source_message",
        cascade="all, delete-orphan",
        uselist=False,
    )
    attempts: Mapped[list["ProcessingAttempt"]] = relationship(
        back_populates="source_message",
        cascade="save-update, merge",
    )
    candidates: Mapped[list["TransactionCandidate"]] = relationship(
        back_populates="source_message",
        cascade="save-update, merge",
    )
    statements: Mapped[list["BankStatement"]] = relationship(
        back_populates="source_message", cascade="save-update, merge"
    )
    observations: Mapped[list["TransactionObservation"]] = relationship(
        back_populates="source_message", cascade="save-update, merge"
    )


class MessageContentMetadata(Base, Timestamped):
    """Parsed headers + metadata for a source message.

    1:1 with :class:`SourceMessage`. Split out so the PII-bearing fields
    (sender, subject, references) can have a different retention policy
    from the deduplication record.
    """

    __tablename__ = "message_content_metadata"
    __table_args__ = (
        UniqueConstraint(
            "source_message_id", name="uq_message_content_metadata_one"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(512), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    message_id_header: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    transaction_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    merchant_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    retain_until: Mapped[datetime | None] = mapped_column(nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(nullable=True)

    source_message: Mapped["SourceMessage"] = relationship(
        back_populates="content_metadata"
    )

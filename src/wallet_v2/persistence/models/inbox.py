"""Inboxes and cursor models.

The DeepSeek V4 review (section 1) flagged that the source-identity
aggregate was missing from the plan. We materialize it here as two
tables:

* :class:`Inbox` — durable identity of a mailbox account/folder, with
  the current ``uid_validity`` and the last-committed ``last_seen_uid``.
  Unique on ``(provider, account_fingerprint, folder)`` so the same
  account can host multiple folders as distinct inboxes without
  colliding.
* :class:`InboxCursorHistory` — append-only log of every cursor advance.
  This is the audit trail the processing worker consults to decide
  whether a fetched message is new or already-seen, and to recover
  after a crash mid-fetch.

Immutability is enforced at the database level by a ``BEFORE UPDATE OR
DELETE`` trigger created in the initial Alembic migration (see
``alembic/versions/0001_initial.py``). The absence of ``updated_at`` on
:class:`InboxCursorHistory` is a secondary signal — the trigger is the
authoritative guard.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.domain.enums import MailboxSourceStatus
from wallet_v2.persistence.base import Base, Immutable, Timestamped

if TYPE_CHECKING:
    from wallet_v2.persistence.models.source_message import SourceMessage


class Inbox(Base, Timestamped):
    """A configured mailbox source.

    Identity is ``(provider, account_fingerprint, folder)``. The same
    account can host multiple folders; each is a distinct inbox row. The
    current cursor is stored inline for fast lookup; the full advance
    history lives in :class:`InboxCursorHistory`.
    """

    __tablename__ = "inboxes"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "account_fingerprint",
            "folder",
            name="uq_inboxes_provider_account_folder",
        ),
        CheckConstraint(
            "length(provider) >= 1",
            name="ck_inboxes_provider_nonempty",
        ),
        CheckConstraint(
            "length(account_fingerprint) = 64",
            name="ck_inboxes_fingerprint_len",
        ),
        CheckConstraint(
            "(uid_validity IS NULL AND last_seen_uid IS NULL) "
            "OR (uid_validity IS NOT NULL AND last_seen_uid IS NOT NULL)",
            name="ck_inboxes_cursor_pair",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'drained', 'revoked')",
            name="ck_inboxes_status",
        ),
        Index("ix_inboxes_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    account_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    folder: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[MailboxSourceStatus] = mapped_column(
        String(16), nullable=False, default=MailboxSourceStatus.ACTIVE
    )
    uid_validity: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    last_seen_uid: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source_messages: Mapped[list["SourceMessage"]] = relationship(
        back_populates="inbox",
        cascade="save-update, merge",
    )


class InboxCursorHistory(Base, Immutable):
    """Append-only record of every cursor advance for an inbox.

    Each row records that, at ``observed_at``, the inbox's committed cursor
    was advanced to ``(uid_validity, last_seen_uid)``. Replays of the
    same cursor are idempotent and produce a row; rollback is by inserting
    a corrected row, never by mutation.

    ``observed_at`` is the *semantic* timestamp — when the cursor advance
    was observed from the mailbox server. ``created_at`` is the *row*
    insertion timestamp. The two are intentionally distinct: an
    out-of-order replay (e.g. after a worker restart) must keep its
    original ``observed_at`` so the cursor history stays monotonic, while
    ``created_at`` records when the row actually landed in the database.

    Immutability is enforced by a PostgreSQL ``BEFORE UPDATE OR DELETE``
    trigger (see the initial migration). The absence of ``updated_at``
    here is a secondary signal, not the primary guard.
    """

    __tablename__ = "inbox_cursor_history"
    __table_args__ = (
        CheckConstraint(
            "uid_validity >= 1",
            name="ck_inbox_cursor_history_uid_validity",
        ),
        CheckConstraint(
            "last_seen_uid >= 1",
            name="ck_inbox_cursor_history_last_seen_uid",
        ),
        Index(
            "ix_inbox_cursor_history_inbox_observed",
            "inbox_id",
            "observed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    inbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inboxes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    uid_validity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_seen_uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

"""Mailbox source and cursor value objects.

The DeepSeek V4 review (section 1) flagged two missing aggregates:

- ``MailboxSource`` — durable identity of a mailbox account/folder, with
  provider account fingerprint and state machine.
- ``MailboxCursor`` — monotonic, idempotent cursor composed of IMAP
  ``UIDVALIDITY`` and ``UID``.

These are domain primitives only. Persistence of the cursor and source state
happens in :mod:`wallet_v2.persistence.models.inbox`; this module is the
type-safe shape used by the (future) mailbox connector and processing worker.

IMAP semantics encoded here:

- ``UIDVALIDITY`` is per-mailbox epoch. When it changes, every prior ``UID``
  is invalidated; the new epoch starts at its own first ``UID``.
- ``UID`` is monotonically increasing within an epoch. Two cursors are equal
  iff their ``uid_validity`` **and** ``last_seen_uid`` match.
- A cursor with a different ``uid_validity`` is **not** comparable to a prior
  one; advancing across epochs requires explicit reset, not silent
  arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wallet_v2.domain.enums import MailboxSourceStatus


class InvalidCursor(ValueError):
    """Raised when a cursor value object is constructed with invalid inputs."""


class InvalidMailbox(ValueError):
    """Raised when a mailbox source is constructed with invalid inputs."""


class CursorEpochMismatch(ValueError):
    """Raised when an operation crosses two different UIDVALIDITY epochs."""


_PROVIDER_LEN_MAX = 32
_FINGERPRINT_LEN = 64
_FOLDER_LEN_MAX = 255


@dataclass(frozen=True, slots=True)
class MailboxCursor:
    """A monotonic, immutable mailbox cursor.

    Attributes:
        uid_validity: IMAP UIDVALIDITY epoch (positive).
        last_seen_uid: highest UID consumed within that epoch (>= 1).

    Two cursors are equal iff both fields are equal. ``last_seen_uid`` of 0
    is rejected because UIDVALIDITY alone is not a fetchable cursor — at
    least one UID must have been observed for the cursor to be meaningful.
    """

    uid_validity: int
    last_seen_uid: int

    def __post_init__(self) -> None:
        if not isinstance(self.uid_validity, int) or isinstance(
            self.uid_validity, bool
        ):
            raise InvalidCursor(
                f"uid_validity must be int, got {type(self.uid_validity).__name__}"
            )
        if not isinstance(self.last_seen_uid, int) or isinstance(
            self.last_seen_uid, bool
        ):
            raise InvalidCursor(
                f"last_seen_uid must be int, got {type(self.last_seen_uid).__name__}"
            )
        if self.uid_validity < 1:
            raise InvalidCursor(
                f"uid_validity must be >= 1, got {self.uid_validity}"
            )
        if self.last_seen_uid < 1:
            raise InvalidCursor(
                f"last_seen_uid must be >= 1, got {self.last_seen_uid}"
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MailboxCursor):
            return NotImplemented
        return (
            self.uid_validity == other.uid_validity
            and self.last_seen_uid == other.last_seen_uid
        )

    def __hash__(self) -> int:
        return hash((self.uid_validity, self.last_seen_uid))

    def __lt__(self, other: "MailboxCursor") -> bool:
        if not isinstance(other, MailboxCursor):
            return NotImplemented  # type: ignore[return-value]
        if self.uid_validity != other.uid_validity:
            raise CursorEpochMismatch(
                "cannot order cursors across uid_validity epochs "
                f"({self.uid_validity} vs {other.uid_validity})"
            )
        return self.last_seen_uid < other.last_seen_uid

    def __le__(self, other: "MailboxCursor") -> bool:
        if not isinstance(other, MailboxCursor):
            return NotImplemented  # type: ignore[return-value]
        if self.uid_validity != other.uid_validity:
            raise CursorEpochMismatch(
                "cannot order cursors across uid_validity epochs "
                f"({self.uid_validity} vs {other.uid_validity})"
            )
        return self.last_seen_uid <= other.last_seen_uid

    def advance(self, other: "MailboxCursor") -> "MailboxCursor":
        """Return the maximum of two same-epoch cursors.

        Raises:
            CursorEpochMismatch: if the two cursors are from different
                UIDVALIDITY epochs. An epoch reset must be handled explicitly
                by the caller (e.g. by replacing the cursor on the source),
                not by silent arithmetic.
        """

        if self.uid_validity != other.uid_validity:
            raise CursorEpochMismatch(
                "cannot advance across uid_validity epochs "
                f"({self.uid_validity} vs {other.uid_validity})"
            )
        return MailboxCursor(
            self.uid_validity, max(self.last_seen_uid, other.last_seen_uid)
        )

    def is_strictly_after(self, other: "MailboxCursor") -> bool:
        """True iff ``self`` is in the same epoch and beyond ``other``."""

        if self.uid_validity != other.uid_validity:
            raise CursorEpochMismatch(
                "cannot compare across uid_validity epochs "
                f"({self.uid_validity} vs {other.uid_validity})"
            )
        return self.last_seen_uid > other.last_seen_uid

    def __str__(self) -> str:
        return f"cursor(v={self.uid_validity},uid={self.last_seen_uid})"

    def __repr__(self) -> str:
        return (
            f"MailboxCursor(uid_validity={self.uid_validity}, "
            f"last_seen_uid={self.last_seen_uid})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid_validity": self.uid_validity,
            "last_seen_uid": self.last_seen_uid,
        }


@dataclass(frozen=True, slots=True)
class MailboxSource:
    """Durable identity of a mailbox account/folder.

    Attributes:
        provider: lowercase connector kind, e.g. ``"imap"`` or ``"gmail"``.
        account_fingerprint: opaque, stable hash that uniquely identifies the
            account within the provider (email address + OAuth sub, hashed).
            Stored verbatim in the ``inboxes`` table.
        folder: provider folder name within the account, e.g. ``"INBOX"``
            or ``"Archive"``. Its spelling is preserved because mailbox
            providers may treat folder names as case-sensitive.
        status: lifecycle state of the source.
        cursor: last-committed cursor, or ``None`` if no message has been
            observed yet.

    Two sources are equal iff ``provider``, ``account_fingerprint``, and
    ``folder`` match; ``status`` and ``cursor`` are mutable operational
    state and do not contribute to identity.  This mirrors the UNIQUE
    constraint on the ``inboxes`` table.
    """

    provider: str
    account_fingerprint: str
    folder: str
    status: MailboxSourceStatus
    cursor: MailboxCursor | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str):
            raise InvalidMailbox(
                f"provider must be str, got {type(self.provider).__name__}"
            )
        if not self.provider:
            raise InvalidMailbox("provider must be non-empty")
        if len(self.provider) > _PROVIDER_LEN_MAX:
            raise InvalidMailbox(
                f"provider must be <= {_PROVIDER_LEN_MAX} chars, "
                f"got {len(self.provider)}"
            )
        if self.provider != self.provider.lower():
            raise InvalidMailbox(
                f"provider must be lowercase, got {self.provider!r}"
            )
        if not isinstance(self.account_fingerprint, str):
            raise InvalidMailbox(
                "account_fingerprint must be str, got "
                f"{type(self.account_fingerprint).__name__}"
            )
        if len(self.account_fingerprint) != _FINGERPRINT_LEN:
            raise InvalidMailbox(
                f"account_fingerprint must be exactly {_FINGERPRINT_LEN} chars "
                f"(hex sha256), got {len(self.account_fingerprint)}"
            )
        if not all(c in "0123456789abcdef" for c in self.account_fingerprint):
            raise InvalidMailbox(
                "account_fingerprint must be lowercase hex sha256, got "
                f"{self.account_fingerprint!r}"
            )
        if not isinstance(self.folder, str):
            raise InvalidMailbox(
                f"folder must be str, got {type(self.folder).__name__}"
            )
        if not self.folder:
            raise InvalidMailbox("folder must be non-empty")
        if len(self.folder) > _FOLDER_LEN_MAX:
            raise InvalidMailbox(
                f"folder must be <= {_FOLDER_LEN_MAX} chars, "
                f"got {len(self.folder)}"
            )
        if not isinstance(self.status, MailboxSourceStatus):
            raise InvalidMailbox(
                f"status must be MailboxSourceStatus, got "
                f"{type(self.status).__name__}"
            )
        if self.cursor is not None and not isinstance(self.cursor, MailboxCursor):
            raise InvalidMailbox(
                "cursor must be MailboxCursor or None, got "
                f"{type(self.cursor).__name__}"
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MailboxSource):
            return NotImplemented
        return (
            self.provider == other.provider
            and self.account_fingerprint == other.account_fingerprint
            and self.folder == other.folder
        )

    def __hash__(self) -> int:
        return hash((self.provider, self.account_fingerprint, self.folder))

    def __str__(self) -> str:
        return f"{self.provider}:{self.account_fingerprint[:8]}/{self.folder}"

    def __repr__(self) -> str:
        return (
            f"MailboxSource(provider={self.provider!r}, "
            f"account_fingerprint={self.account_fingerprint!r}, "
            f"folder={self.folder!r}, "
            f"status={self.status!r}, cursor={self.cursor!r})"
        )

    def with_cursor(self, cursor: MailboxCursor | None) -> "MailboxSource":
        """Return a copy of this source with an updated cursor.

        The identity (provider + fingerprint + folder) is preserved; only
        the operational cursor state changes.  This is the only sanctioned
        way to update a source's cursor: the source identity itself is
        immutable.

        Raises:
            CursorEpochMismatch: if *cursor* has a different ``uid_validity``
                than the current cursor.  Use :meth:`reset_cursor` to
                explicitly acknowledge a UIDVALIDITY change.
        """

        if cursor is not None and self.cursor is not None:
            if cursor.uid_validity != self.cursor.uid_validity:
                raise CursorEpochMismatch(
                    "cursor replacement across uid_validity epochs must be "
                    "explicitly acknowledged via reset_cursor(); "
                    "refusing silent advance"
                )
        return MailboxSource(
            provider=self.provider,
            account_fingerprint=self.account_fingerprint,
            folder=self.folder,
            status=self.status,
            cursor=cursor,
        )

    def with_status(self, status: MailboxSourceStatus) -> "MailboxSource":
        """Return a copy of this source with an updated status."""

        return MailboxSource(
            provider=self.provider,
            account_fingerprint=self.account_fingerprint,
            folder=self.folder,
            status=status,
            cursor=self.cursor,
        )

    def reset_cursor(self, cursor: MailboxCursor | None) -> "MailboxSource":
        """Return a copy with a new cursor, acknowledging a UIDVALIDITY change.

        Unlike :meth:`with_cursor`, this method permits replacing the cursor
        with one that has a different ``uid_validity``.  This is the
        sanctioned way to handle server-side mailbox recreation or other
        events that invalidate the previous UIDVALIDITY epoch.

        The identity (provider + fingerprint + folder) is preserved; only
        the operational cursor state changes.
        """

        return MailboxSource(
            provider=self.provider,
            account_fingerprint=self.account_fingerprint,
            folder=self.folder,
            status=self.status,
            cursor=cursor,
        )

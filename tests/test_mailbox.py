"""Tests for the MailboxCursor and MailboxSource domain value objects.

Locks the invariants from the DeepSeek V4 review (section 1):

* Cursor equality is on ``(uid_validity, last_seen_uid)``.
* Operations across different ``uid_validity`` epochs raise.
* Source identity is ``(provider, account_fingerprint, folder)``; the cursor
  and status are operational state and do not contribute to identity.
* ``with_cursor`` refuses cross-epoch cursor replacement;
  ``reset_cursor`` explicitly permits it.
"""

from __future__ import annotations

import hashlib

import pytest

from wallet_v2.domain.enums import MailboxSourceStatus
from wallet_v2.domain.mailbox import (
    CursorEpochMismatch,
    InvalidCursor,
    InvalidMailbox,
    MailboxCursor,
    MailboxSource,
)


_FINGERPRINT_LEN = 64
_FOLDER_LEN_MAX = 255


def _fingerprint(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


_FP = _fingerprint("user@example.com")


class TestMailboxCursorConstruction:
    def test_accepts_positive_pair(self) -> None:
        c = MailboxCursor(uid_validity=1, last_seen_uid=1)
        assert c.uid_validity == 1
        assert c.last_seen_uid == 1

    @pytest.mark.parametrize(
        "uid_validity,last_seen_uid",
        [(0, 1), (1, 0), (-1, 1), (1, -1)],
    )
    def test_rejects_non_positive(
        self, uid_validity: int, last_seen_uid: int
    ) -> None:
        with pytest.raises(InvalidCursor):
            MailboxCursor(uid_validity=uid_validity, last_seen_uid=last_seen_uid)

    def test_rejects_bool(self) -> None:
        with pytest.raises(InvalidCursor):
            MailboxCursor(uid_validity=True, last_seen_uid=1)  # type: ignore[arg-type]

    def test_rejects_float(self) -> None:
        with pytest.raises(InvalidCursor):
            MailboxCursor(uid_validity=1, last_seen_uid=1.0)  # type: ignore[arg-type]


class TestMailboxCursorIdentity:
    def test_equal_when_pair_matches(self) -> None:
        assert MailboxCursor(1, 100) == MailboxCursor(1, 100)

    def test_not_equal_when_uid_differs(self) -> None:
        assert MailboxCursor(1, 100) != MailboxCursor(1, 200)

    def test_not_equal_when_uid_validity_differs(self) -> None:
        assert MailboxCursor(1, 100) != MailboxCursor(2, 100)

    def test_hash_matches_equality(self) -> None:
        assert hash(MailboxCursor(1, 100)) == hash(MailboxCursor(1, 100))
        assert {MailboxCursor(1, 100), MailboxCursor(1, 100)} == {
            MailboxCursor(1, 100)
        }


class TestMailboxCursorEpochMismatch:
    def test_lt_across_epochs_raises(self) -> None:
        with pytest.raises(CursorEpochMismatch):
            _ = MailboxCursor(1, 100) < MailboxCursor(2, 50)

    def test_advance_across_epochs_raises(self) -> None:
        with pytest.raises(CursorEpochMismatch):
            MailboxCursor(1, 100).advance(MailboxCursor(2, 200))

    def test_is_strictly_after_across_epochs_raises(self) -> None:
        with pytest.raises(CursorEpochMismatch):
            MailboxCursor(2, 100).is_strictly_after(MailboxCursor(1, 100))


class TestMailboxCursorAdvance:
    def test_advance_returns_max_same_epoch(self) -> None:
        a = MailboxCursor(1, 100)
        b = MailboxCursor(1, 200)
        assert a.advance(b) == MailboxCursor(1, 200)
        assert b.advance(a) == MailboxCursor(1, 200)

    def test_advance_is_commutative(self) -> None:
        a = MailboxCursor(1, 100)
        b = MailboxCursor(1, 200)
        assert a.advance(b) == b.advance(a)

    def test_is_strictly_after_same_epoch(self) -> None:
        assert MailboxCursor(1, 200).is_strictly_after(MailboxCursor(1, 100))
        assert not MailboxCursor(1, 100).is_strictly_after(MailboxCursor(1, 200))
        assert not MailboxCursor(1, 100).is_strictly_after(MailboxCursor(1, 100))


class TestMailboxCursorSerialization:
    def test_roundtrip(self) -> None:
        c = MailboxCursor(7, 42)
        d = c.to_dict()
        assert d == {"uid_validity": 7, "last_seen_uid": 42}


class TestMailboxSourceIdentity:
    def test_identity_is_provider_fingerprint_and_folder(self) -> None:
        a = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
            cursor=MailboxCursor(1, 100),
        )
        b = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.PAUSED,
            cursor=None,
        )
        assert a == b
        assert hash(a) == hash(b)

    def test_different_folder_not_equal(self) -> None:
        inbox = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        archive = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="archive",
            status=MailboxSourceStatus.ACTIVE,
        )
        assert inbox != archive
        assert hash(inbox) != hash(archive)

    def test_different_provider_not_equal(self) -> None:
        a = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        b = MailboxSource(
            provider="gmail",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        assert a != b

    def test_different_fingerprint_not_equal(self) -> None:
        a = MailboxSource(
            provider="imap",
            account_fingerprint=_fingerprint("a@example.com"),
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        b = MailboxSource(
            provider="imap",
            account_fingerprint=_fingerprint("b@example.com"),
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        assert a != b


class TestMailboxSourceValidation:
    def test_accepts_valid_minimal(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        assert src.folder == "inbox"

    def test_rejects_uppercase_provider(self) -> None:
        with pytest.raises(InvalidMailbox, match="provider must be lowercase"):
            MailboxSource(
                provider="IMAP",
                account_fingerprint=_FP,
                folder="inbox",
                status=MailboxSourceStatus.ACTIVE,
            )

    def test_rejects_wrong_length_fingerprint(self) -> None:
        with pytest.raises(InvalidMailbox, match="account_fingerprint must be exactly"):
            MailboxSource(
                provider="imap",
                account_fingerprint="not-a-sha256",
                folder="inbox",
                status=MailboxSourceStatus.ACTIVE,
            )

    def test_rejects_uppercase_hex_fingerprint(self) -> None:
        with pytest.raises(InvalidMailbox, match="lowercase hex sha256"):
            MailboxSource(
                provider="imap",
                account_fingerprint="A" * 64,
                folder="inbox",
                status=MailboxSourceStatus.ACTIVE,
            )

    def test_rejects_non_enum_status(self) -> None:
        with pytest.raises(InvalidMailbox, match="status must be MailboxSourceStatus"):
            MailboxSource(
                provider="imap",
                account_fingerprint=_FP,
                folder="inbox",
                status="active",  # type: ignore[arg-type]
            )

    def test_rejects_empty_folder(self) -> None:
        with pytest.raises(InvalidMailbox, match="folder must be non-empty"):
            MailboxSource(
                provider="imap",
                account_fingerprint=_FP,
                folder="",
                status=MailboxSourceStatus.ACTIVE,
            )

    def test_preserves_uppercase_provider_folder(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="INBOX",
            status=MailboxSourceStatus.ACTIVE,
        )
        assert src.folder == "INBOX"

    def test_rejects_non_string_folder(self) -> None:
        with pytest.raises(InvalidMailbox, match="folder must be str"):
            MailboxSource(
                provider="imap",
                account_fingerprint=_FP,
                folder=123,  # type: ignore[arg-type]
                status=MailboxSourceStatus.ACTIVE,
            )

    def test_rejects_too_long_folder(self) -> None:
        with pytest.raises(InvalidMailbox, match=f"<= {_FOLDER_LEN_MAX} chars"):
            MailboxSource(
                provider="imap",
                account_fingerprint=_FP,
                folder="a" * (_FOLDER_LEN_MAX + 1),
                status=MailboxSourceStatus.ACTIVE,
            )

    def test_accepts_max_length_folder(self) -> None:
        folder = "a" * _FOLDER_LEN_MAX
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder=folder,
            status=MailboxSourceStatus.ACTIVE,
        )
        assert src.folder == folder


class TestMailboxSourceWithCursor:
    def test_with_cursor_preserves_identity(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        updated = src.with_cursor(MailboxCursor(1, 100))
        assert updated == src
        assert updated.cursor == MailboxCursor(1, 100)

    def test_with_cursor_preserves_folder(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="archive",
            status=MailboxSourceStatus.ACTIVE,
        )
        updated = src.with_cursor(MailboxCursor(1, 100))
        assert updated.folder == "archive"

    def test_with_cursor_across_epochs_raises(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
            cursor=MailboxCursor(1, 100),
        )
        with pytest.raises(CursorEpochMismatch):
            src.with_cursor(MailboxCursor(2, 50))

    def test_with_status_preserves_identity_and_cursor(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
            cursor=MailboxCursor(1, 100),
        )
        paused = src.with_status(MailboxSourceStatus.PAUSED)
        assert paused == src
        assert paused.cursor == src.cursor
        assert paused.status == MailboxSourceStatus.PAUSED


class TestMailboxSourceResetCursor:
    def test_reset_preserves_identity(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
            cursor=MailboxCursor(1, 100),
        )
        updated = src.reset_cursor(MailboxCursor(3, 1))
        assert updated == src
        assert updated.cursor == MailboxCursor(3, 1)

    def test_reset_allows_epoch_change(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
            cursor=MailboxCursor(1, 100),
        )
        updated = src.reset_cursor(MailboxCursor(2, 50))
        assert updated.cursor == MailboxCursor(2, 50)

    def test_reset_can_clear_to_none(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
            cursor=MailboxCursor(1, 100),
        )
        updated = src.reset_cursor(None)
        assert updated.cursor is None

    def test_reset_accepts_none_when_already_none(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        updated = src.reset_cursor(None)
        assert updated.cursor is None

    def test_reset_preserves_folder(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        updated = src.reset_cursor(MailboxCursor(5, 10))
        assert updated.folder == "inbox"
        assert updated.provider == "imap"
        assert updated.account_fingerprint == _FP

    def test_with_cursor_still_rejects_after_reset_allows(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
            cursor=MailboxCursor(1, 100),
        )
        # reset_cursor can cross epochs
        src = src.reset_cursor(MailboxCursor(2, 50))
        assert src.cursor == MailboxCursor(2, 50)
        # with_cursor still refuses cross-epoch after a reset
        with pytest.raises(CursorEpochMismatch):
            src.with_cursor(MailboxCursor(3, 1))


class TestMailboxSourceRepresentation:
    def test_str_includes_folder(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        assert "/inbox" in str(src)

    def test_repr_includes_folder(self) -> None:
        src = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        assert "folder='inbox'" in repr(src)

    def test_hash_set_distinguishes_by_folder(self) -> None:
        inbox = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="inbox",
            status=MailboxSourceStatus.ACTIVE,
        )
        archive = MailboxSource(
            provider="imap",
            account_fingerprint=_FP,
            folder="archive",
            status=MailboxSourceStatus.ACTIVE,
        )
        assert len({inbox, archive}) == 2

"""Regression tests for IMAP non-mutating fetch behavior."""

from __future__ import annotations

from datetime import date
from email.message import EmailMessage

import pytest

from wallet_v2.adapters.imap_mailbox import ImapMailboxReader


class _FakeImap:
    def __init__(self) -> None:
        message = EmailMessage()
        message["From"] = "alerts@example.test"
        message["To"] = "wallet@example.test"
        message["Subject"] = "Synthetic receipt"
        message["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        message.set_content("Synthetic body")
        self.raw = message.as_bytes()
        self.selected: tuple[str, bool] | None = None
        self.search_queries: list[tuple[object, ...]] = []
        self.fetch_queries: list[tuple[bytes, str]] = []
        self.logout_called = False

    def login(self, username: str, password: str) -> tuple[str, list[bytes]]:
        assert username == "user@example.test"
        assert password == "password"
        return "OK", [b"logged in"]

    def select(self, folder: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.selected = (folder, readonly)
        return "OK", [b"1"]

    def uid(self, command: str, *args: object) -> tuple[str, list[object]]:
        if command == "search":
            self.search_queries.append(args)
            return "OK", [b"41 42"]
        assert command == "fetch"
        uid, query = args
        assert isinstance(uid, bytes)
        assert isinstance(query, str)
        self.fetch_queries.append((uid, query))
        return "OK", [(b"42 (BODY[] {123})", self.raw), b")"]

    def response(self, name: str) -> tuple[str, list[bytes]]:
        assert name == "UIDVALIDITY"
        return "OK", [b"17"]

    def logout(self) -> None:
        self.logout_called = True


def test_fetch_uses_readonly_select_and_body_peek_without_seen_mutation() -> None:
    fake = _FakeImap()
    reader = ImapMailboxReader(
        host="imap.example.test",
        port=993,
        username="user@example.test",
        password="password",
        client_factory=lambda host, port: fake,
    )

    messages = reader.fetch_unseen(limit=1)

    assert fake.selected == ("INBOX", True)
    assert fake.search_queries == [(None, "UNSEEN")]
    assert fake.fetch_queries == [(b"42", "(BODY.PEEK[] FLAGS)")]
    assert fake.logout_called
    assert len(messages) == 1
    assert messages[0].message_uid == 42
    assert messages[0].uid_validity == 17
    assert messages[0].body_text.strip() == "Synthetic body"


def test_uidvalidity_response_code_name_is_accepted() -> None:
    class _ResponseCodeFake(_FakeImap):
        def response(self, name: str) -> tuple[str, list[bytes]]:
            assert name == "UIDVALIDITY"
            return "UIDVALIDITY", [b"17"]

    fake = _ResponseCodeFake()
    reader = ImapMailboxReader(
        host="imap.example.test",
        port=993,
        username="user@example.test",
        password="password",
        client_factory=lambda host, port: fake,
    )

    assert reader.fetch_unseen(limit=1)[0].uid_validity == 17


def test_fetch_on_date_searches_all_messages_in_exact_day_range() -> None:
    fake = _FakeImap()
    reader = ImapMailboxReader(
        host="imap.example.test",
        port=993,
        username="user@example.test",
        password="password",
        client_factory=lambda host, port: fake,
    )

    messages = reader.fetch_on_date(day=date(2026, 7, 19))

    assert fake.selected == ("INBOX", True)
    assert fake.search_queries == [
        (None, "SINCE", "19-Jul-2026", "BEFORE", "20-Jul-2026")
    ]
    assert fake.fetch_queries == [
        (b"41", "(BODY.PEEK[] FLAGS)"),
        (b"42", "(BODY.PEEK[] FLAGS)"),
    ]
    assert len(messages) == 2


def test_fetch_uids_uses_peek_without_a_search() -> None:
    fake = _FakeImap()
    reader = ImapMailboxReader(
        host="imap.example.test",
        port=993,
        username="user@example.test",
        password="password",
        client_factory=lambda host, port: fake,
    )

    messages = reader.fetch_uids(uids=(41, 42, 41))

    assert fake.selected == ("INBOX", True)
    assert fake.search_queries == []
    assert fake.fetch_queries == [
        (b"41", "(BODY.PEEK[] FLAGS)"),
        (b"42", "(BODY.PEEK[] FLAGS)"),
    ]
    assert [message.message_uid for message in messages] == [41, 42]


def test_html_only_message_uses_visible_text_without_css() -> None:
    message = EmailMessage()
    message.set_content(
        "<style>.hidden { color: red; }</style><script>ignore()</script>"
        "<p>Approved purchase RD$ 4,915.00 at PriceSmart</p>",
        subtype="html",
    )

    body = ImapMailboxReader._body_text(message)

    assert body == "Approved purchase RD$ 4,915.00 at PriceSmart"
    assert "hidden" not in body
    assert "ignore" not in body


def test_pdf_attachment_text_is_included(monkeypatch: pytest.MonkeyPatch) -> None:
    message = EmailMessage()
    message.set_content("A statement is attached.")
    message.add_attachment(
        b"not-a-real-pdf", maintype="application", subtype="pdf", filename="statement.pdf"
    )
    monkeypatch.setattr(
        ImapMailboxReader,
        "_pdf_attachment_text",
        staticmethod(lambda part: "PDF transaction amount DOP 100.00"),
    )

    body = ImapMailboxReader._body_text(message)

    assert "A statement is attached." in body
    assert "PDF transaction amount DOP 100.00" in body

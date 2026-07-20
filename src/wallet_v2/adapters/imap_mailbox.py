"""Read-only IMAP adapter that never changes message flags."""

from __future__ import annotations

import hashlib
import imaplib
import re
from datetime import date, datetime, timedelta, timezone
from email import message_from_bytes
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from typing import Callable, Sequence

from pypdf import PdfReader

from wallet_v2.application.contracts import MailboxMessage


_MAX_PDF_ATTACHMENT_BYTES = 5 * 1024 * 1024
_MAX_PDF_PAGES = 30
_MAX_ATTACHMENT_TEXT_CHARACTERS = 20_000


class _VisibleTextParser(HTMLParser):
    """Collect visible HTML text while excluding CSS and scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


class ImapMailboxReader:
    """Fetch unseen messages with ``EXAMINE`` and ``BODY.PEEK[]`` only.

    The adapter deliberately exposes no flag-changing method. ``readonly=True``
    on IMAP ``select`` maps to the protocol's read-only mailbox selection; the
    PEEK fetch avoids the implicit ``\\Seen`` side effect of a normal body fetch.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        folder: str = "INBOX",
        provider: str = "imap",
        client_factory: Callable[[str, int], imaplib.IMAP4_SSL] = imaplib.IMAP4_SSL,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.folder = folder
        self.provider = provider
        self.client_factory = client_factory

    def fetch_unseen(self, *, limit: int) -> Sequence[MailboxMessage]:
        """Fetch at most ``limit`` unseen messages without changing flags."""

        return self._fetch(search_criteria=("UNSEEN",), limit=limit)

    def fetch_on_date(self, *, day: date) -> Sequence[MailboxMessage]:
        """Fetch every message whose IMAP internal date falls on ``day``.

        This deliberately does not include ``UNSEEN`` in the search criteria:
        a historical, date-bounded run means all messages on that date. IMAP's
        ``BEFORE`` criterion is exclusive, so the next calendar day gives an
        exact one-day range without requiring provider-specific date parsing.
        """

        next_day = day + timedelta(days=1)
        return self._fetch(
            search_criteria=(
                "SINCE",
                day.strftime("%d-%b-%Y"),
                "BEFORE",
                next_day.strftime("%d-%b-%Y"),
            ),
            limit=None,
        )

    def fetch_uids(self, *, uids: Sequence[int]) -> Sequence[MailboxMessage]:
        """Fetch explicit IMAP UIDs for an operator-approved reprocess run."""

        normalized_uids = tuple(dict.fromkeys(uids))
        if not normalized_uids or any(uid < 1 for uid in normalized_uids):
            raise ValueError("uids must contain one or more positive IMAP UIDs")
        client = self._select_readonly()
        try:
            return self._messages_for_uids(
                client, [str(uid).encode() for uid in normalized_uids], self._uid_validity(client)
            )
        finally:
            self._logout(client)

    def _fetch(
        self, *, search_criteria: tuple[str, ...], limit: int | None
    ) -> Sequence[MailboxMessage]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        client = self._select_readonly()
        try:
            status, data = client.uid("search", None, *search_criteria)
            if status != "OK":
                raise RuntimeError("IMAP message search failed")
            uids = data[0].split()
            if limit is not None:
                uids = uids[-limit:]
            return self._messages_for_uids(client, uids, self._uid_validity(client))
        finally:
            self._logout(client)

    def _select_readonly(self) -> imaplib.IMAP4_SSL:
        client = self.client_factory(self.host, self.port)
        status, _ = client.login(self.username, self.password)
        if status != "OK":
            self._logout(client)
            raise RuntimeError("IMAP login failed")
        status, _ = client.select(self.folder, readonly=True)
        if status != "OK":
            self._logout(client)
            raise RuntimeError("IMAP read-only mailbox selection failed")
        return client

    def _messages_for_uids(
        self, client: imaplib.IMAP4_SSL, uids: Sequence[bytes], uid_validity: int
    ) -> Sequence[MailboxMessage]:
        messages: list[MailboxMessage] = []
        for raw_uid in uids:
            status, fetched = client.uid("fetch", raw_uid, "(BODY.PEEK[] FLAGS)")
            if status != "OK" or not fetched:
                raise RuntimeError(f"IMAP PEEK fetch failed for UID {raw_uid!r}")
            raw = next(
                (item[1] for item in fetched if isinstance(item, tuple) and isinstance(item[1], bytes)),
                None,
            )
            if raw is None:
                raise RuntimeError("IMAP PEEK response did not contain a message body")
            parsed = message_from_bytes(raw)
            messages.append(
                MailboxMessage(
                    provider=self.provider,
                    account_fingerprint=hashlib.sha256(self.username.lower().encode()).hexdigest(),
                    folder=self.folder,
                    uid_validity=uid_validity,
                    message_uid=int(raw_uid),
                    sender=parsed.get("From"),
                    recipient=parsed.get("To"),
                    subject=parsed.get("Subject"),
                    message_id_header=parsed.get("Message-ID"),
                    received_at=self._message_date(parsed),
                    body_text=self._body_text(parsed),
                )
            )
        return messages

    @staticmethod
    def _logout(client: imaplib.IMAP4_SSL) -> None:
        try:
            client.logout()
        except Exception:
            pass

    @staticmethod
    def _uid_validity(client: imaplib.IMAP4_SSL) -> int:
        status, response = client.response("UIDVALIDITY")
        # IMAP4.response() returns the requested response-code name on some
        # servers and ``OK`` on others. Both forms contain the same value.
        if status not in {"OK", "UIDVALIDITY"} or not response or response[0] is None:
            raise RuntimeError("IMAP server did not provide UIDVALIDITY")
        return int(response[0])

    @staticmethod
    def _message_date(message: Message) -> datetime:
        raw_date = message.get("Date")
        if raw_date:
            try:
                parsed = parsedate_to_datetime(raw_date)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, IndexError):
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _body_text(message: Message) -> str:
        """Build bounded extraction input from plain text, HTML, and PDFs."""

        parts = tuple(message.walk()) if message.is_multipart() else (message,)
        segments: list[str] = []
        for part in parts:
            if part.get_content_type() == "text/plain":
                text = ImapMailboxReader._part_text(part)
                if text:
                    segments.append(text)
            elif part.get_content_type() == "text/html":
                text = ImapMailboxReader._visible_html_text(part)
                if text:
                    segments.append(text)
            elif ImapMailboxReader._is_pdf_attachment(part):
                text = ImapMailboxReader._pdf_attachment_text(part)
                if text:
                    segments.append(text)
        return "\n\n".join(segments)[:_MAX_ATTACHMENT_TEXT_CHARACTERS]

    @staticmethod
    def _part_text(part: Message) -> str:
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return ""
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace").strip()

    @staticmethod
    def _visible_html_text(part: Message) -> str:
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return ""
        parser = _VisibleTextParser()
        parser.feed(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()

    @staticmethod
    def _is_pdf_attachment(part: Message) -> bool:
        filename = part.get_filename() or ""
        return part.get_content_type() == "application/pdf" or filename.lower().endswith(".pdf")

    @staticmethod
    def _pdf_attachment_text(part: Message) -> str:
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or len(payload) > _MAX_PDF_ATTACHMENT_BYTES:
            return ""
        try:
            reader = PdfReader(BytesIO(payload))
            if reader.is_encrypted:
                return ""
            pages: list[str] = []
            for page in reader.pages[:_MAX_PDF_PAGES]:
                pages.append(page.extract_text() or "")
            return "\n".join(pages).strip()[:_MAX_ATTACHMENT_TEXT_CHARACTERS]
        except Exception:
            return ""

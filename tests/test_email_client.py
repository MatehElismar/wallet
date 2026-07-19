"""Regression tests for mailbox-safe email retrieval."""

from datetime import datetime
from email.message import EmailMessage
import unittest

from email_client import IMAPEmailClient


class _FakeIMAPConnection:
    def __init__(self, raw_message: bytes):
        self.raw_message = raw_message
        self.selected_folders = []
        self.search_queries = []
        self.fetch_calls = []

    def select_folder(self, folder):
        self.selected_folders.append(folder)

    def search(self, query):
        self.search_queries.append(query)
        return [42]

    def fetch(self, message_ids, data_items):
        self.fetch_calls.append((message_ids, data_items))
        # IMAP returns BODY[] even when BODY.PEEK[] was requested.
        return {42: {b"BODY[]": self.raw_message}}


class IMAPEmailClientTests(unittest.TestCase):
    def test_fetch_uses_body_peek_without_marking_message_seen(self):
        message = EmailMessage()
        message["Subject"] = "Payment receipt"
        message["From"] = "alerts@example.com"
        message["Date"] = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
        message.set_content("Your purchase of $10.00 was approved.")

        connection = _FakeIMAPConnection(message.as_bytes())
        client = IMAPEmailClient("imap.example.com", 993, "user@example.com", "password")
        client.connection = connection

        emails = client.fetch_new_emails()

        self.assertEqual(connection.selected_folders, ["INBOX"])
        self.assertEqual(connection.search_queries, ["UNSEEN"])
        self.assertEqual(connection.fetch_calls, [([42], [b"BODY.PEEK[]"])])
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0].email_id, "imap_42")
        self.assertIn("purchase of $10.00", emails[0].body)


if __name__ == "__main__":
    unittest.main()

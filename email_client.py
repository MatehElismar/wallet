import logging
from datetime import datetime
from typing import List, Tuple, Optional
from email_parser import EmailMetadata
import config

logger = logging.getLogger(__name__)

class EmailClient:
    """Base email client interface."""

    def fetch_new_emails(self) -> List[EmailMetadata]:
        """Fetch unread emails since last run."""
        raise NotImplementedError

    def mark_as_processed(self, email_id: str):
        """Mark an email as processed (label, flag, etc)."""
        raise NotImplementedError


class IMAPEmailClient(EmailClient):
    """IMAP-based email client for Gmail or any IMAP provider."""

    def __init__(self, host: str = None, port: int = None, email: str = None, password: str = None):
        self.host = host or config.IMAP_HOST
        self.port = port or config.IMAP_PORT
        self.email = email or config.IMAP_EMAIL
        self.password = password or config.IMAP_PASSWORD
        self.connection = None

    def connect(self):
        """Establish IMAP connection."""
        try:
            import imapclient
            self.connection = imapclient.IMAPClient(self.host, port=self.port, ssl=True)
            self.connection.login(self.email, self.password)
            logger.info(f"Connected to {self.host} as {self.email}")
        except Exception as e:
            logger.error(f"Failed to connect to IMAP: {e}")
            raise

    def disconnect(self):
        """Close IMAP connection."""
        if self.connection:
            try:
                self.connection.logout()
            except:
                pass

    def fetch_new_emails(self) -> List[EmailMetadata]:
        """Fetch unread emails from INBOX."""
        emails = []
        try:
            if not self.connection:
                self.connect()

            # Select inbox and search for unread
            self.connection.select_folder("INBOX")
            msg_ids = self.connection.search("UNSEEN")

            if not msg_ids:
                logger.info("No new emails")
                return emails

            # Fetch headers and body
            response = self.connection.fetch(msg_ids, ["ENVELOPE", "BODY[TEXT]", "BODY[HTML]"])

            for msg_id, data in response.items():
                try:
                    envelope = data[b"ENVELOPE"]
                    subject = envelope.subject.decode() if isinstance(envelope.subject, bytes) else envelope.subject
                    sender = envelope.from_[0]
                    sender_name = sender.name.decode() if isinstance(sender.name, bytes) else sender.name
                    sender_email = sender.mailbox.decode() + "@" + sender.host.decode()
                    sender_str = f"{sender_name or ''} <{sender_email}>".strip()

                    # Get received date
                    received_date = envelope.date or datetime.utcnow()

                    # Get body (prefer TEXT over HTML)
                    body = None
                    if b"BODY[TEXT]" in data:
                        body = data[b"BODY[TEXT]"].decode()
                    elif b"BODY[HTML]" in data:
                        from email_parser import EmailParser
                        parser = EmailParser()
                        html_body = data[b"BODY[HTML]"].decode()
                        body = parser.extract_text_from_html(html_body)

                    if body:
                        email_meta = EmailMetadata(
                            email_id=f"imap_{msg_id}",
                            subject=subject,
                            sender=sender_str,
                            received_date=received_date,
                            body=body,
                        )
                        emails.append(email_meta)

                except Exception as e:
                    logger.warning(f"Failed to parse email {msg_id}: {e}")

            logger.info(f"Fetched {len(emails)} new emails")
            return emails

        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            return emails

    def mark_as_processed(self, email_id: str):
        """Mark email as read."""
        try:
            if not self.connection:
                self.connect()

            msg_id = int(email_id.replace("imap_", ""))
            self.connection.set_flags(msg_id, [b"\\Seen"])
            logger.debug(f"Marked email {email_id} as read")
        except Exception as e:
            logger.warning(f"Failed to mark email as processed: {e}")


class MockEmailClient(EmailClient):
    """Mock email client for testing without real email setup."""

    def __init__(self):
        self.emails = [
            EmailMetadata(
                email_id="mock_1",
                subject="Starbucks Receipt",
                sender="receipt@starbucks.com",
                received_date=datetime.utcnow(),
                body="Your purchase of $5.50 at Starbucks Store #1234 on May 28, 2025 at 2:30 PM",
            ),
            EmailMetadata(
                email_id="mock_2",
                subject="Direct Deposit Confirmation",
                sender="payroll@company.com",
                received_date=datetime.utcnow(),
                body="Your salary deposit of $5000.00 has been processed to your account",
            ),
        ]

    def fetch_new_emails(self) -> List[EmailMetadata]:
        logger.info(f"Mock: Returning {len(self.emails)} mock emails")
        return self.emails

    def mark_as_processed(self, email_id: str):
        logger.debug(f"Mock: Marked {email_id} as processed")


def create_email_client() -> EmailClient:
    """Factory function to create the appropriate email client."""
    if config.EMAIL_PROVIDER == "gmail":
        logger.info("Using Gmail API (not yet implemented, falling back to mock)")
        return MockEmailClient()
    elif config.EMAIL_PROVIDER == "imap":
        return IMAPEmailClient()
    else:
        logger.warning(f"Unknown email provider: {config.EMAIL_PROVIDER}, using mock")
        return MockEmailClient()

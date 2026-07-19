import logging
from datetime import datetime
from typing import List, Tuple, Optional, Dict
from email_parser import EmailMetadata

logger = logging.getLogger(__name__)

class EmailClient:
    """Base email client interface."""

    def fetch_new_emails(self, days_back: int = 0) -> List[EmailMetadata]:
        """Fetch unread emails since last run."""
        raise NotImplementedError

    def mark_as_processed(self, email_id: str):
        """Mark an email as processed (label, flag, etc)."""
        raise NotImplementedError


class IMAPEmailClient(EmailClient):
    """IMAP-based email client for Gmail or any IMAP provider."""

    def __init__(self, host: str, port: int, email: str, password: str):
        self.host = host
        self.port = port
        self.email = email
        self.password = password
        self.connection = None

    def connect(self):
        """Establish IMAP connection."""
        try:
            import imapclient
            self.connection = imapclient.IMAPClient(self.host, port=self.port, ssl=True)
            # Gmail App Passwords are 16 chars; strip spaces added for readability
            password = self.password.replace(" ", "") if self.password else self.password
            self.connection.login(self.email, password)
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

    def fetch_new_emails(self, days_back: int = 0) -> List[EmailMetadata]:
        """Fetch emails from INBOX.

        Args:
            days_back: If 0, fetch only unread. If >0, fetch from last N days.
        """
        emails = []
        try:
            if not self.connection:
                self.connect()

            # Select inbox and search for emails
            self.connection.select_folder("INBOX")

            if days_back > 0:
                # Search for emails from the past N days
                from datetime import datetime, timedelta
                since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
                search_query = f"SINCE {since_date}"
                logger.info(f"Searching for emails since {since_date}")
                msg_ids = self.connection.search(search_query)
            else:
                # Search for unread emails only
                msg_ids = self.connection.search("UNSEEN")

            if not msg_ids:
                logger.info("No new emails")
                return emails

            # PEEK is essential: a regular RFC822/BODY fetch marks the message \Seen.
            # IMAP servers return the fetched payload under BODY[] (without PEEK).
            response = self.connection.fetch(msg_ids, [b"BODY.PEEK[]"])

            for msg_id, data in response.items():
                try:
                    # Parse the raw message returned by the non-mutating PEEK fetch.
                    import email as email_lib
                    raw_message = data.get(b"BODY[]") or data.get(b"BODY.PEEK[]")
                    if raw_message is None:
                        raise KeyError("IMAP BODY.PEEK[] response did not contain a message body")
                    msg = email_lib.message_from_bytes(raw_message)

                    subject = msg.get("Subject", "(no subject)")
                    sender = msg.get("From", "unknown")
                    date_str = msg.get("Date")

                    # Parse date
                    from email.utils import parsedate_to_datetime
                    try:
                        received_date = parsedate_to_datetime(date_str) if date_str else datetime.utcnow()
                    except:
                        received_date = datetime.utcnow()

                    # Extract body (prefer text over HTML)
                    body = None
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type == "text/plain":
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                            elif content_type == "text/html" and not body:
                                from email_parser import EmailParser
                                parser = EmailParser()
                                html_body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                body = parser.extract_text_from_html(html_body)
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                    if body:
                        email_meta = EmailMetadata(
                            email_id=f"imap_{msg_id}",
                            subject=subject,
                            sender=sender,
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

    def fetch_new_emails(self, days_back: int = 0) -> List[EmailMetadata]:
        logger.info(f"Mock: Returning {len(self.emails)} mock emails")
        return self.emails

    def mark_as_processed(self, email_id: str):
        logger.debug(f"Mock: Marked {email_id} as processed")


class GmailAPIClient(EmailClient):
    """Gmail API client using OAuth 2.0."""

    def __init__(self, credentials_file: str, token_file: str):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Gmail API using OAuth 2.0."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.service_account import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth import default
            import os
            import pickle

            SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

            creds = None
            # If token.json exists, use it
            if os.path.exists(self.token_file):
                try:
                    with open(self.token_file, "rb") as token:
                        creds = pickle.load(token)
                except Exception as e:
                    logger.warning(f"Failed to load token: {e}")

            # If creds expired or missing, refresh/reauth
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    logger.info("Refreshing Gmail auth token")
                    creds.refresh(Request())
                else:
                    logger.info("Initiating Gmail OAuth flow (opens browser)")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                # Save token for future use
                with open(self.token_file, "wb") as token:
                    pickle.dump(creds, token)
                logger.info(f"Gmail token saved to {self.token_file}")

            # Build Gmail service
            from googleapiclient.discovery import build
            self.service = build("gmail", "v1", credentials=creds)
            logger.info("Connected to Gmail API")

        except FileNotFoundError:
            logger.error(f"credentials.json not found at {self.credentials_file}")
            logger.error("See GMAIL_SETUP.md for instructions on generating credentials")
            raise
        except Exception as e:
            logger.error(f"Gmail authentication failed: {e}")
            logger.error("See GMAIL_SETUP.md for troubleshooting")
            raise

    def fetch_new_emails(self, days_back: int = 0) -> List[EmailMetadata]:
        """Fetch unread emails from Gmail."""
        if not self.service:
            logger.error("Gmail service not initialized")
            return []

        emails = []
        try:
            # Search for unread emails
            results = self.service.users().messages().list(
                userId="me",
                q="is:unread",
                maxResults=10
            ).execute()

            messages = results.get("messages", [])
            if not messages:
                logger.info("No new unread emails in Gmail")
                return emails

            for message in messages:
                try:
                    msg_data = self.service.users().messages().get(
                        userId="me",
                        id=message["id"],
                        format="full"
                    ).execute()

                    headers = msg_data["payload"]["headers"]
                    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
                    sender = next((h["value"] for h in headers if h["name"] == "From"), "unknown")
                    date_str = next((h["value"] for h in headers if h["name"] == "Date"), None)

                    # Parse date
                    from email.utils import parsedate_to_datetime
                    try:
                        received_date = parsedate_to_datetime(date_str) if date_str else datetime.utcnow()
                    except:
                        received_date = datetime.utcnow()

                    # Get body
                    body = self._get_email_body(msg_data)

                    email_meta = EmailMetadata(
                        email_id=f"gmail_{message['id']}",
                        subject=subject,
                        sender=sender,
                        received_date=received_date,
                        body=body,
                    )
                    emails.append(email_meta)

                except Exception as e:
                    logger.warning(f"Failed to parse Gmail message: {e}")

            logger.info(f"Fetched {len(emails)} new emails from Gmail")
            return emails

        except Exception as e:
            logger.error(f"Failed to fetch Gmail emails: {e}")
            return emails

    def _get_email_body(self, msg_data: Dict) -> str:
        """Extract plain text body from Gmail message."""
        from email_parser import EmailParser

        try:
            if "parts" in msg_data["payload"]:
                for part in msg_data["payload"]["parts"]:
                    if part["mimeType"] == "text/plain":
                        data = part["body"].get("data", "")
                        if data:
                            import base64
                            return base64.urlsafe_b64decode(data).decode("utf-8")
                    elif part["mimeType"] == "text/html":
                        data = part["body"].get("data", "")
                        if data:
                            import base64
                            html = base64.urlsafe_b64decode(data).decode("utf-8")
                            parser = EmailParser()
                            return parser.extract_text_from_html(html)
            else:
                # Single part message
                data = msg_data["payload"]["body"].get("data", "")
                if data:
                    import base64
                    return base64.urlsafe_b64decode(data).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to extract email body: {e}")

        return "(unable to extract email body)"

    def mark_as_processed(self, email_id: str):
        """Mark email as read in Gmail."""
        if not self.service:
            return

        try:
            msg_id = email_id.replace("gmail_", "")
            self.service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
            logger.debug(f"Marked Gmail email {email_id} as read")
        except Exception as e:
            logger.warning(f"Failed to mark Gmail email as read: {e}")

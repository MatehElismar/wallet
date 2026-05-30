import logging
from datetime import datetime
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import html2text

logger = logging.getLogger(__name__)

class EmailMetadata:
    def __init__(self, email_id: str, subject: str, sender: str, received_date: datetime, body: str,
                 account_name: str = None, account_email: str = None):
        self.email_id = email_id
        self.subject = subject
        self.sender = sender
        self.received_date = received_date
        self.body = body
        self.account_name = account_name
        self.account_email = account_email

    def to_dict(self):
        return {
            "email_id": self.email_id,
            "subject": self.subject,
            "sender": self.sender,
            "received_date": self.received_date.isoformat(),
            "body": self.body,
            "account_name": self.account_name,
            "account_email": self.account_email,
        }

class EmailParser:
    """Extract and parse email content, convert HTML to plain text."""

    def __init__(self, max_email_chars: int = 4000):
        self.max_email_chars = max_email_chars
        self.h = html2text.HTML2Text()
        self.h.ignore_links = False
        self.h.ignore_images = True

    def extract_text_from_html(self, html_content: str) -> str:
        """Convert HTML email content to plain text."""
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            # Get text
            text = soup.get_text()
            # Break into lines and remove leading/trailing space
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = "\n".join(chunk for chunk in chunks if chunk)
            return text
        except Exception as e:
            logger.warning(f"Failed to parse HTML, returning raw content: {e}")
            return html_content

    def prepare_for_llm(self, metadata: EmailMetadata) -> str:
        """Prepare email content for LLM processing with metadata."""
        lines = [
            f"From: {metadata.sender}",
            f"Subject: {metadata.subject}",
            f"Date: {metadata.received_date.isoformat()}",
            "",
            "--- Email Body ---",
            metadata.body,
        ]
        content = "\n".join(lines)
        # Truncate to max chars
        if len(content) > self.max_email_chars:
            content = content[: self.max_email_chars] + "\n[... truncated ...]"
        return content

    def is_likely_transaction(self, subject: str, body: str) -> bool:
        """Quick heuristic: is this likely a financial transaction email?"""
        spam_keywords = [
            "unsubscribe",
            "marketing",
            "newsletter",
            "promotional",
            "verify your email",
            "confirm your identity",
        ]
        combined = (subject + " " + body).lower()
        if any(keyword in combined for keyword in spam_keywords):
            return False
        return True

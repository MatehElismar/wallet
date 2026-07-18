import re
import logging
from datetime import datetime
from typing import Tuple, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Negative rules: clearly NOT a financial transaction ──────────────────────
NOT_TRANSACTION_RULES = [
    # Unsubscribe / marketing
    ("unsubscribe",              "keyword:unsubscribe"),
    ("marketing",                "keyword:marketing"),
    ("newsletter",               "keyword:newsletter"),
    ("promotional",              "keyword:promotional"),
    # Email / identity verification
    ("verify your email",        "keyword:verify_email"),
    ("confirm your identity",    "keyword:confirm_identity"),
    ("verification code",        "keyword:verification_code"),
    ("one-time password",        "keyword:otp"),
    ("código de verificación",   "keyword:otp_es"),
    ("código de seguridad",      "keyword:security_code_es"),
    ("confirma tu correo",       "keyword:verify_email_es"),
    ("verifica tu email",        "keyword:verify_email_es2"),
    ("verifica tu cuenta",       "keyword:verify_account_es"),
    # Account / security notifications (no money involved)
    ("your account statement",   "keyword:account_statement"),
    ("balance inquiry",          "keyword:balance_inquiry"),
    ("new login",                "keyword:new_login"),
    ("sign-in attempt",          "keyword:sign_in"),
    ("security alert",           "keyword:security_alert"),
    ("suspicious activity",      "keyword:suspicious_activity"),
    ("new sign-in",              "keyword:new_sign_in"),
    ("account access",           "keyword:account_access"),
    ("alerta de seguridad",      "keyword:security_alert_es"),
    ("inicio de sesión",         "keyword:login_es"),
    # CI / DevOps notifications
    ("run failed:",              "keyword:ci_run_failed"),
    ("workflow failed",          "keyword:ci_workflow_failed"),
    ("build failed",             "keyword:ci_build_failed"),
    ("deployment failed",        "keyword:ci_deploy_failed"),
    # Spanish holiday / event marketing
    ("feliz día",                "keyword:holiday_marketing_es"),
    ("feliz navidad",            "keyword:holiday_marketing_es"),
    ("descuento",                "keyword:discount_es"),
    ("oferta especial",          "keyword:offer_es"),
    ("celebra",                  "keyword:celebrate_marketing_es"),
]

# ── Subject-level patterns (checked against subject only, pre-lowercased) ────
import re as _re

NOT_TRANSACTION_SUBJECT_PATTERNS = [
    # GitHub / GitLab issue and PR notifications: [owner/repo] Something
    (_re.compile(r"^\[[\w.\-]+/[\w.\-]+\]"), "pattern:vcs_notification"),
    # Pull requests, issues, CI runs
    (_re.compile(r"\b(?:pull request|merge request|opened an issue|commented on)\b", _re.I),
     "pattern:vcs_activity"),
]

# ── Positive rules: strong transaction signals ───────────────────────────────
# Applied only when an amount pattern is also present.
_AMOUNT_RE = re.compile(
    r"[\$\€\£\¥₡₹]\s*[\d,]+\.?\d*"
    r"|[\d,]+\.?\d*\s*(?:USD|EUR|GBP|DOP|CRC|MXN|COP|GTQ|HNL|NIO|PAB|PEN|PYG|UYU)\b",
    re.IGNORECASE,
)

TRANSACTION_RULES = [
    (re.compile(r"\b(?:your purchase|your payment|payment received|payment confirmed)\b", re.I),
     "keyword:payment_confirmation"),
    (re.compile(r"\b(?:has been charged|amount charged|se ha cobrado|se ha debitado|fue cobrado)\b", re.I),
     "keyword:charged"),
    (re.compile(r"\b(?:transaction|receipt|comprobante|recibo de pago)\b", re.I),
     "keyword:transaction_receipt"),
    (re.compile(r"\b(?:amount debited|amount credited|debito|credito|fue debitado)\b", re.I),
     "keyword:debit_credit"),
    (re.compile(r"\border (?:confirmed|placed|shipped)\b", re.I),
     "keyword:order_confirmed"),
    (re.compile(r"\b(?:pago exitoso|pago realizado|compra exitosa|cargo exitoso)\b", re.I),
     "keyword:payment_success_es"),
    (re.compile(r"\b(?:transferencia realizada|transferencia exitosa)\b", re.I),
     "keyword:transfer_es"),
]


class EmailMetadata:
    def __init__(self, email_id: str, subject: str, sender: str, received_date: datetime,
                 body: str, account_name: str = None, account_email: str = None,
                 bank_hint: str = None):
        self.email_id = email_id
        self.subject = subject
        self.sender = sender
        self.received_date = received_date
        self.body = body
        self.account_name = account_name   # name of the email inbox, not the Wallet account
        self.account_email = account_email
        self.bank_hint = bank_hint         # canonical bank key from inbox config, e.g. "bhd"

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

    def extract_text_from_html(self, html_content: str) -> str:
        """Convert HTML email content to plain text."""
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            return "\n".join(chunk for chunk in chunks if chunk)
        except Exception as e:
            logger.warning(f"Failed to parse HTML: {e}")
            return html_content

    def prepare_for_llm(self, metadata: EmailMetadata) -> str:
        """Prepare email content for LLM processing."""
        lines = [
            f"From: {metadata.sender}",
            f"Subject: {metadata.subject}",
            f"Date: {metadata.received_date.isoformat()}",
            "",
            "--- Email Body ---",
            metadata.body,
        ]
        content = "\n".join(lines)
        if len(content) > self.max_email_chars:
            content = content[: self.max_email_chars] + "\n[... truncated ...]"
        return content

    def classify_by_heuristic(self, subject: str, body: str) -> Tuple[str, Optional[str]]:
        """
        Classify email using keyword and pattern rules.

        Returns:
            ('not_transaction', 'keyword:newsletter') — clearly not a financial transaction
            ('transaction', 'keyword:payment_confirmation') — strong positive signals present
            ('uncertain', None) — cannot determine; should be sent to LLM classifier
        """
        subject_lower = subject.lower()
        combined = (subject + " " + body).lower()

        # Subject-level pattern rules (e.g. GitHub/GitLab bracket notation)
        for pattern, rule in NOT_TRANSACTION_SUBJECT_PATTERNS:
            if pattern.search(subject_lower):
                return ("not_transaction", rule)

        # Keyword rules on combined subject + body
        for keyword, rule in NOT_TRANSACTION_RULES:
            if keyword in combined:
                return ("not_transaction", rule)

        # Positive rules: require an amount pattern AND a transaction keyword
        has_amount = bool(_AMOUNT_RE.search(combined))
        if has_amount:
            for pattern, rule in TRANSACTION_RULES:
                if pattern.search(combined):
                    return ("transaction", rule)

        return ("uncertain", None)

    def is_likely_transaction(self, subject: str, body: str) -> bool:
        """Backwards-compatible wrapper around classify_by_heuristic."""
        result, _ = self.classify_by_heuristic(subject, body)
        return result != "not_transaction"

"""Multi-account email orchestration."""

import json
import logging
import os
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from email_client import (
    create_email_client,
    EmailClient,
    GmailAPIClient,
    IMAPEmailClient,
)
from email_parser import EmailParser

logger = logging.getLogger(__name__)


@dataclass
class EmailAccount:
    """Single email account configuration."""

    name: str
    provider: str  # "gmail" or "imap"
    enabled: bool
    host: Optional[str] = None
    port: Optional[int] = None
    email: Optional[str] = None
    password: Optional[str] = None
    credentials_file: Optional[str] = None
    token_file: Optional[str] = None
    category_prefix: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dict for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    @staticmethod
    def from_dict(data: Dict) -> "EmailAccount":
        """Create from dict."""
        # Only extract fields that exist in EmailAccount
        fields = {
            "name": data.get("name"),
            "provider": data.get("provider"),
            "enabled": data.get("enabled", True),
            "host": data.get("host"),
            "port": data.get("port"),
            "email": data.get("email"),
            "password": data.get("password"),
            "credentials_file": data.get("credentials_file"),
            "token_file": data.get("token_file"),
            "category_prefix": data.get("category_prefix"),
        }
        # Remove None values for optional fields
        return EmailAccount(**{k: v for k, v in fields.items() if v is not None or k in ["name", "provider", "enabled"]})


class MultiAccountConfig:
    """Load and manage multiple email accounts."""

    def __init__(self, config_file: str = "email_accounts.json"):
        self.config_file = config_file
        self.accounts: List[EmailAccount] = []
        self.load()

    def load(self):
        """Load accounts from JSON file."""
        if not os.path.exists(self.config_file):
            logger.warning(f"Config file {self.config_file} not found, using defaults")
            self._load_defaults()
            return

        try:
            with open(self.config_file, "r") as f:
                data = json.load(f)
            self.accounts = [
                EmailAccount.from_dict(acc)
                for acc in data.get("accounts", [])
            ]
            logger.info(f"Loaded {len(self.accounts)} email accounts from {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self._load_defaults()

    def _load_defaults(self):
        """Load default account from environment."""
        import config

        if config.EMAIL_PROVIDER == "imap":
            self.accounts = [
                EmailAccount(
                    name="Default IMAP",
                    provider="imap",
                    enabled=True,
                    host=config.IMAP_HOST,
                    port=config.IMAP_PORT,
                    email=config.IMAP_EMAIL,
                    password=config.IMAP_PASSWORD,
                )
            ]
        elif config.EMAIL_PROVIDER == "gmail":
            self.accounts = [
                EmailAccount(
                    name="Default Gmail API",
                    provider="gmail",
                    enabled=True,
                    credentials_file=config.GMAIL_CREDENTIALS_FILE,
                    token_file=config.GMAIL_TOKEN_FILE,
                )
            ]
        else:
            logger.info("No email accounts configured, using mock")

    def get_enabled_accounts(self) -> List[EmailAccount]:
        """Get all enabled accounts."""
        return [acc for acc in self.accounts if acc.enabled]

    def add_account(self, account: EmailAccount):
        """Add a new account."""
        self.accounts.append(account)

    def save(self):
        """Save accounts to JSON file."""
        try:
            data = {"accounts": [acc.to_dict() for acc in self.accounts]}
            with open(self.config_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.accounts)} accounts to {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")


class MultiAccountEmailClient:
    """Orchestrate multiple email accounts."""

    def __init__(self, config_file: str = "email_accounts.json"):
        self.config = MultiAccountConfig(config_file)
        self.clients: Dict[str, EmailClient] = {}
        self._init_clients()

    def _init_clients(self):
        """Initialize email client for each enabled account."""
        for account in self.config.get_enabled_accounts():
            try:
                if account.provider == "gmail":
                    client = GmailAPIClient(
                        credentials_file=account.credentials_file,
                        token_file=account.token_file,
                    )
                elif account.provider == "imap":
                    client = IMAPEmailClient(
                        host=account.host,
                        port=account.port,
                        email=account.email,
                        password=account.password,
                    )
                else:
                    logger.warning(f"Unknown provider for {account.name}: {account.provider}")
                    continue

                self.clients[account.name] = client
                logger.info(f"Initialized {account.name}")
            except Exception as e:
                logger.error(f"Failed to initialize {account.name}: {e}")

    def fetch_all_emails(self) -> Dict[str, list]:
        """Fetch emails from all accounts.

        Returns: {account_name: [EmailMetadata, ...], ...}
        """
        all_emails = {}

        for account in self.config.get_enabled_accounts():
            if account.name not in self.clients:
                logger.warning(f"No client for {account.name}, skipping")
                continue

            try:
                client = self.clients[account.name]
                emails = client.fetch_new_emails()

                # Add account info to each email for tracking
                for email in emails:
                    email.account_name = account.name
                    email.account_email = account.email
                    # Optionally prefix category
                    if account.category_prefix and hasattr(email, "category_prefix"):
                        email.category_prefix = account.category_prefix

                all_emails[account.name] = emails
                logger.info(f"{account.name}: Fetched {len(emails)} emails")

            except Exception as e:
                logger.error(f"Failed to fetch from {account.name}: {e}")
                all_emails[account.name] = []

        return all_emails

    def mark_as_processed(self, account_name: str, email_id: str):
        """Mark email as processed in a specific account."""
        if account_name not in self.clients:
            logger.warning(f"No client for {account_name}")
            return

        try:
            client = self.clients[account_name]
            client.mark_as_processed(email_id)
        except Exception as e:
            logger.warning(f"Failed to mark {email_id} as processed: {e}")

    def stats(self) -> Dict:
        """Get stats on all accounts."""
        return {
            "total_accounts": len(self.config.accounts),
            "enabled_accounts": len(self.config.get_enabled_accounts()),
            "initialized_clients": len(self.clients),
            "accounts": [
                {
                    "name": acc.name,
                    "provider": acc.provider,
                    "enabled": acc.enabled,
                    "email": acc.email or "(api)",
                }
                for acc in self.config.accounts
            ],
        }

import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum

logger = logging.getLogger(__name__)

class ProcessingStatus(str, Enum):
    PENDING = "pending"
    LLM_PROCESSING = "llm_processing"
    LLM_SKIP = "llm_skip"
    LLM_ERROR = "llm_error"
    VALIDATION_ERROR = "validation_error"
    API_PENDING = "api_pending"
    API_SUCCESS = "api_success"
    API_CLIENT_ERROR = "api_client_error"
    API_SERVER_ERROR = "api_server_error"

class StateStore:
    """SQLite-backed state store for email processing."""

    def __init__(self, db_path: str = "wallet.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_emails (
                    email_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    subject TEXT,
                    sender TEXT,
                    received_date TEXT,
                    llm_output TEXT,
                    wallet_record_id TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS account_cache (
                    account_id TEXT PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    cached_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS category_cache (
                    category_id TEXT PRIMARY KEY,
                    category_name TEXT NOT NULL,
                    cached_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def record_email(self, email_id: str, subject: str, sender: str, received_date: str):
        """Record a new email with pending status."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO processed_emails
                (email_id, status, subject, sender, received_date, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (email_id, ProcessingStatus.PENDING.value, subject, sender, received_date, now, now))
            conn.commit()

    def update_status(self, email_id: str, status: ProcessingStatus, error_message: str = None, llm_output: str = None, wallet_record_id: str = None):
        """Update the processing status of an email."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE processed_emails
                SET status = ?, error_message = ?, llm_output = ?, wallet_record_id = ?, updated_at = ?
                WHERE email_id = ?
            """, (status.value, error_message, llm_output, wallet_record_id, now, email_id))
            conn.commit()

    def increment_retry(self, email_id: str):
        """Increment retry count for an email."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE processed_emails
                SET retry_count = retry_count + 1
                WHERE email_id = ?
            """, (email_id,))
            conn.commit()

    def is_processed(self, email_id: str) -> bool:
        """Check if an email has already been processed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM processed_emails WHERE email_id = ?", (email_id,))
            result = cursor.fetchone()
        return result is not None

    def get_email_status(self, email_id: str) -> Optional[Dict]:
        """Get full status record for an email."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM processed_emails WHERE email_id = ?", (email_id,))
            result = cursor.fetchone()
            if result:
                return dict(result)
        return None

    def get_emails_by_status(self, status: ProcessingStatus, limit: int = 50) -> List[Dict]:
        """Get all emails with a specific status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM processed_emails
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (status.value, limit))
            results = [dict(row) for row in cursor.fetchall()]
        return results

    def cache_accounts(self, accounts: List[Dict]):
        """Cache account ID → name mappings."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM account_cache")
            for acc in accounts:
                cursor.execute("""
                    INSERT INTO account_cache (account_id, account_name, cached_at)
                    VALUES (?, ?, ?)
                """, (acc["id"], acc["name"], now))
            conn.commit()

    def cache_categories(self, categories: List[Dict]):
        """Cache category ID → name mappings."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM category_cache")
            for cat in categories:
                cursor.execute("""
                    INSERT INTO category_cache (category_id, category_name, cached_at)
                    VALUES (?, ?, ?)
                """, (cat["id"], cat["name"], now))
            conn.commit()

    def get_account_map(self) -> Dict[str, str]:
        """Get account_name → account_id mapping from cache."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT account_name, account_id FROM account_cache")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_category_map(self) -> Dict[str, str]:
        """Get category_name → category_id mapping from cache."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category_name, category_id FROM category_cache")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def stats(self) -> Dict:
        """Get overall pipeline stats."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM processed_emails
                GROUP BY status
            """)
            stats = {row[0]: row[1] for row in cursor.fetchall()}
        return stats

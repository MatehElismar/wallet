import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum

logger = logging.getLogger(__name__)

class RequestStatus(str, Enum):
    """Status of email processing through the system."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class ClassificationStatus(str, Enum):
    """Classification decision made about the email."""
    PENDING = "pending"
    NOT_TRANSACTION = "not_transaction"  # Heuristic filter rejected
    CLASSIFIED = "classified"  # LLM successfully classified
    INVALID = "invalid"  # Classification failed validation
    LLM_ERROR = "llm_error"  # LLM couldn't process
    POSTED_TO_WALLET = "posted_to_wallet"  # Successfully sent to Wallet

# Keep for backwards compatibility
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
                    request_status TEXT NOT NULL,
                    classification_status TEXT NOT NULL,
                    subject TEXT,
                    sender TEXT,
                    received_date TEXT,
                    email_body TEXT,
                    llm_prompt TEXT,
                    llm_output TEXT,
                    llm_reasoning TEXT,
                    validation_errors TEXT,
                    decision_notes TEXT,
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

    def record_email(self, email_id: str, subject: str, sender: str, received_date: str, email_body: str = None):
        """Record a new email with pending status."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO processed_emails
                (email_id, request_status, classification_status, subject, sender, received_date, email_body, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (email_id, RequestStatus.PENDING.value, ClassificationStatus.PENDING.value,
                  subject, sender, received_date, email_body, now, now))
            conn.commit()

    def update_status(self, email_id: str, status: ProcessingStatus = None,
                     request_status: RequestStatus = None, classification_status: ClassificationStatus = None,
                     error_message: str = None, llm_output: str = None, wallet_record_id: str = None,
                     llm_prompt: str = None, llm_reasoning: str = None, validation_errors: str = None,
                     decision_notes: str = None):
        """Update email status with separate request and classification tracking.

        Args:
            request_status: System processing status (pending, processing, completed, failed)
            classification_status: Decision about the email (not_transaction, classified, invalid, etc)
            status: (deprecated) Old single status field - converted to request/classification
        """
        now = datetime.utcnow().isoformat()

        # Map old status to new dual-status system for backwards compatibility
        if status and not request_status and not classification_status:
            if status == ProcessingStatus.PENDING:
                request_status = RequestStatus.PENDING
                classification_status = ClassificationStatus.PENDING
            elif status == ProcessingStatus.LLM_PROCESSING:
                request_status = RequestStatus.PROCESSING
                classification_status = ClassificationStatus.PENDING
            elif status == ProcessingStatus.LLM_SKIP:
                request_status = RequestStatus.COMPLETED
                classification_status = ClassificationStatus.NOT_TRANSACTION
            elif status == ProcessingStatus.LLM_ERROR:
                request_status = RequestStatus.FAILED
                classification_status = ClassificationStatus.LLM_ERROR
            elif status == ProcessingStatus.VALIDATION_ERROR:
                request_status = RequestStatus.COMPLETED
                classification_status = ClassificationStatus.INVALID
            elif status == ProcessingStatus.API_PENDING:
                request_status = RequestStatus.PROCESSING
                classification_status = ClassificationStatus.CLASSIFIED
            elif status == ProcessingStatus.API_SUCCESS:
                request_status = RequestStatus.COMPLETED
                classification_status = ClassificationStatus.POSTED_TO_WALLET
            elif status == ProcessingStatus.API_CLIENT_ERROR:
                request_status = RequestStatus.FAILED
                classification_status = ClassificationStatus.INVALID
            elif status == ProcessingStatus.API_SERVER_ERROR:
                request_status = RequestStatus.FAILED
                classification_status = ClassificationStatus.CLASSIFIED

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE processed_emails
                SET request_status = ?, classification_status = ?, error_message = ?,
                    llm_output = ?, wallet_record_id = ?, llm_prompt = ?,
                    llm_reasoning = ?, validation_errors = ?, decision_notes = ?,
                    updated_at = ?
                WHERE email_id = ?
            """, (request_status.value if request_status else None,
                  classification_status.value if classification_status else None,
                  error_message, llm_output, wallet_record_id, llm_prompt,
                  llm_reasoning, validation_errors, decision_notes, now, email_id))
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
            cursor.execute("SELECT request_status FROM processed_emails WHERE email_id = ?", (email_id,))
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

    def get_emails_by_status(self, status: ProcessingStatus = None,
                            request_status: RequestStatus = None,
                            classification_status: ClassificationStatus = None,
                            limit: int = 50) -> List[Dict]:
        """Get emails by request or classification status.

        Args:
            status: (deprecated) Old single status - maps to request/classification
            request_status: Filter by request processing status
            classification_status: Filter by classification decision
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Support old API for backwards compatibility
            if status and not request_status and not classification_status:
                if status == ProcessingStatus.API_SUCCESS:
                    classification_status = ClassificationStatus.POSTED_TO_WALLET
                elif status == ProcessingStatus.VALIDATION_ERROR:
                    classification_status = ClassificationStatus.INVALID

            if classification_status:
                cursor.execute("""
                    SELECT * FROM processed_emails
                    WHERE classification_status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (classification_status.value, limit))
            elif request_status:
                cursor.execute("""
                    SELECT * FROM processed_emails
                    WHERE request_status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (request_status.value, limit))
            else:
                cursor.execute("""
                    SELECT * FROM processed_emails
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))

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
        """Get overall pipeline stats (request and classification)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Request status stats
            cursor.execute("""
                SELECT request_status, COUNT(*) as count
                FROM processed_emails
                GROUP BY request_status
            """)
            request_stats = {row[0]: row[1] for row in cursor.fetchall()}

            # Classification status stats
            cursor.execute("""
                SELECT classification_status, COUNT(*) as count
                FROM processed_emails
                GROUP BY classification_status
            """)
            classification_stats = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "request_status": request_stats,
            "classification_status": classification_stats,
        }

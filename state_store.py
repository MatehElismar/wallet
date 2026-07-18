import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum

logger = logging.getLogger(__name__)


class RequestStatus(str, Enum):
    """Lifecycle of the email through the system."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ClassificationStatus(str, Enum):
    """What the email IS — regardless of how it was determined."""
    PENDING = "pending"
    NOT_TRANSACTION = "not_transaction"
    TRANSACTION = "transaction"


class ClassificationMethod(str, Enum):
    """How the classification was determined."""
    HEURISTIC = "heuristic"
    LLM = "llm"


class ExtractionStatus(str, Enum):
    """State of data extraction for confirmed transactions."""
    NOT_ATTEMPTED = "not_attempted"
    PENDING = "pending"
    EXTRACTED = "extracted"
    INVALID = "invalid"
    ERROR = "error"
    POSTED = "posted"
    API_ERROR = "api_error"


# Kept for backwards compatibility with audit.py / llm_analysis.py
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
        self._migrate_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id         TEXT PRIMARY KEY,
                    phase          INTEGER NOT NULL,
                    started_at     TEXT NOT NULL,
                    completed_at   TEXT,
                    inbox_accounts TEXT,
                    emails_fetched INTEGER DEFAULT 0,
                    classified     INTEGER DEFAULT 0,
                    extracted      INTEGER DEFAULT 0,
                    posted         INTEGER DEFAULT 0,
                    errors         INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_emails (
                    -- Identity
                    email_id            TEXT PRIMARY KEY,
                    run_id              TEXT REFERENCES pipeline_runs(run_id),
                    inbox_account       TEXT,

                    -- Pipeline status
                    request_status      TEXT NOT NULL DEFAULT 'pending',
                    classification_status TEXT NOT NULL DEFAULT 'pending',
                    classification_method TEXT,
                    heuristic_rule      TEXT,
                    extraction_status   TEXT,

                    -- Email metadata
                    subject             TEXT,
                    sender              TEXT,
                    received_date       TEXT,
                    email_body          TEXT,

                    -- Classification step
                    classify_prompt          TEXT,
                    classify_raw_response    TEXT,
                    classify_is_transaction  INTEGER,
                    classify_reason          TEXT,
                    classify_confidence      TEXT,

                    -- Extraction step
                    extract_prompt           TEXT,
                    extract_raw_response     TEXT,
                    account_resolution       TEXT,

                    -- Extracted wallet fields (flat columns for queryability)
                    extracted_amount         REAL,
                    extracted_date           TEXT,
                    extracted_payment_type   TEXT,
                    extracted_payee          TEXT,
                    extracted_note           TEXT,
                    extracted_account_name   TEXT,
                    extracted_account_id     TEXT,
                    extracted_category_name  TEXT,
                    extracted_category_id    TEXT,
                    extracted_skip_reason    TEXT,

                    -- Validation & posting
                    validation_result    TEXT,
                    wallet_record_id     TEXT,

                    -- Errors & metadata
                    error_message        TEXT,
                    decision_notes       TEXT,
                    retry_count          INTEGER DEFAULT 0,
                    created_at           TEXT NOT NULL,
                    updated_at           TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS account_cache (
                    account_id   TEXT PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    cached_at    TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS category_cache (
                    category_id   TEXT PRIMARY KEY,
                    category_name TEXT NOT NULL,
                    cached_at     TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS label_cache (
                    label_id   TEXT PRIMARY KEY,
                    label_name TEXT NOT NULL,
                    cached_at  TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_interactions (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id         TEXT NOT NULL,
                    run_id           TEXT,
                    interaction_type TEXT NOT NULL DEFAULT 'extract',
                    provider         TEXT NOT NULL,
                    model            TEXT NOT NULL,
                    system_prompt    TEXT,
                    user_prompt      TEXT,
                    raw_response     TEXT,
                    parsed_output    TEXT,
                    parsing_error    TEXT,
                    success          BOOLEAN DEFAULT 0,
                    timestamp        TEXT NOT NULL,
                    FOREIGN KEY (email_id) REFERENCES processed_emails(email_id)
                )
            """)
            conn.commit()

    def _migrate_db(self):
        """Add new columns to existing tables. Idempotent."""
        new_columns = [
            # pipeline_runs support
            ("processed_emails", "run_id",              "TEXT"),
            ("processed_emails", "inbox_account",        "TEXT"),
            # classify step
            ("processed_emails", "classify_prompt",          "TEXT"),
            ("processed_emails", "classify_raw_response",    "TEXT"),
            ("processed_emails", "classify_is_transaction",  "INTEGER"),
            ("processed_emails", "classify_reason",          "TEXT"),
            ("processed_emails", "classify_confidence",      "TEXT"),
            # extract step
            ("processed_emails", "extract_prompt",           "TEXT"),
            ("processed_emails", "extract_raw_response",     "TEXT"),
            ("processed_emails", "account_resolution",       "TEXT"),
            # extracted wallet fields
            ("processed_emails", "extracted_amount",         "REAL"),
            ("processed_emails", "extracted_date",           "TEXT"),
            ("processed_emails", "extracted_payment_type",   "TEXT"),
            ("processed_emails", "extracted_payee",          "TEXT"),
            ("processed_emails", "extracted_note",           "TEXT"),
            ("processed_emails", "extracted_account_name",   "TEXT"),
            ("processed_emails", "extracted_account_id",     "TEXT"),
            ("processed_emails", "extracted_category_name",  "TEXT"),
            ("processed_emails", "extracted_category_id",    "TEXT"),
            ("processed_emails", "extracted_skip_reason",    "TEXT"),
            # llm_interactions run tracking
            ("llm_interactions", "run_id", "TEXT"),
        ]

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            for table, column, col_type in new_columns:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    logger.info(f"Migration: added {table}.{column}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Migrate old classification_status values → new schema (idempotent)
            cursor.execute("""
                UPDATE processed_emails
                SET extraction_status = CASE classification_status
                    WHEN 'not_transaction'  THEN 'not_attempted'
                    WHEN 'invalid'          THEN 'invalid'
                    WHEN 'llm_error'        THEN 'error'
                    WHEN 'posted_to_wallet' THEN 'posted'
                    WHEN 'classified'       THEN 'extracted'
                    ELSE 'pending'
                END
                WHERE extraction_status IS NULL
            """)

            cursor.execute("""
                UPDATE processed_emails
                SET classification_status = CASE classification_status
                    WHEN 'not_transaction'  THEN 'not_transaction'
                    WHEN 'invalid'          THEN 'transaction'
                    WHEN 'llm_error'        THEN 'pending'
                    WHEN 'posted_to_wallet' THEN 'transaction'
                    WHEN 'classified'       THEN 'transaction'
                    ELSE 'pending'
                END
                WHERE classification_status NOT IN ('pending', 'not_transaction', 'transaction')
            """)

            cursor.execute("""
                UPDATE processed_emails SET classification_method = 'heuristic'
                WHERE classification_method IS NULL AND classification_status = 'not_transaction'
            """)
            cursor.execute("""
                UPDATE processed_emails SET classification_method = 'llm'
                WHERE classification_method IS NULL AND classification_status != 'pending'
            """)
            cursor.execute("""
                UPDATE llm_interactions SET interaction_type = 'extract'
                WHERE interaction_type IS NULL
            """)

            conn.commit()

    # ── Pipeline runs ─────────────────────────────────────────────────────────

    def create_run(self, run_id: str, phase: int, inbox_accounts: List[str]):
        """Record the start of a pipeline run."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO pipeline_runs (run_id, phase, started_at, inbox_accounts)
                VALUES (?, ?, ?, ?)
            """, (run_id, phase, now, json.dumps(inbox_accounts)))
            conn.commit()

    def complete_run(self, run_id: str, stats: Dict):
        """Record the completion of a pipeline run."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE pipeline_runs
                SET completed_at   = ?,
                    emails_fetched = ?,
                    classified     = ?,
                    extracted      = ?,
                    posted         = ?,
                    errors         = ?
                WHERE run_id = ?
            """, (
                now,
                stats.get("fetched", 0),
                stats.get("classified", 0),
                stats.get("extracted", 0),
                stats.get("posted", 0),
                stats.get("errors", 0),
                run_id,
            ))
            conn.commit()

    def get_recent_runs(self, limit: int = 10) -> List[Dict]:
        """Get recent pipeline runs."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    # ── Email records ─────────────────────────────────────────────────────────

    def record_email(self, email_id: str, subject: str, sender: str,
                     received_date: str, email_body: str = None,
                     run_id: str = None, inbox_account: str = None):
        """Record a new email with pending status."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO processed_emails
                (email_id, run_id, inbox_account, request_status, classification_status,
                 subject, sender, received_date, email_body, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (email_id, run_id, inbox_account,
                  RequestStatus.PENDING.value, ClassificationStatus.PENDING.value,
                  subject, sender, received_date, email_body, now, now))
            conn.commit()

    def update_status(self, email_id: str,
                      # Pipeline state
                      request_status: RequestStatus = None,
                      classification_status: ClassificationStatus = None,
                      classification_method: ClassificationMethod = None,
                      heuristic_rule: str = None,
                      extraction_status: ExtractionStatus = None,
                      # Classification step
                      classify_prompt: str = None,
                      classify_raw_response: str = None,
                      classify_is_transaction: bool = None,
                      classify_reason: str = None,
                      classify_confidence: str = None,
                      # Extraction step
                      extract_prompt: str = None,
                      extract_raw_response: str = None,
                      account_resolution: str = None,
                      # Extracted wallet fields
                      extracted_amount: float = None,
                      extracted_date: str = None,
                      extracted_payment_type: str = None,
                      extracted_payee: str = None,
                      extracted_note: str = None,
                      extracted_account_name: str = None,
                      extracted_account_id: str = None,
                      extracted_category_name: str = None,
                      extracted_category_id: str = None,
                      extracted_skip_reason: str = None,
                      # Validation & posting
                      validation_result: str = None,
                      wallet_record_id: str = None,
                      # Errors
                      error_message: str = None,
                      decision_notes: str = None):
        """Update email state. Non-None fields overwrite; None fields preserve existing values."""
        now = datetime.utcnow().isoformat()

        classify_int = None
        if classify_is_transaction is not None:
            classify_int = 1 if classify_is_transaction else 0

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE processed_emails
                SET request_status           = COALESCE(?, request_status),
                    classification_status    = COALESCE(?, classification_status),
                    classification_method    = COALESCE(?, classification_method),
                    heuristic_rule           = COALESCE(?, heuristic_rule),
                    extraction_status        = COALESCE(?, extraction_status),
                    classify_prompt          = COALESCE(?, classify_prompt),
                    classify_raw_response    = COALESCE(?, classify_raw_response),
                    classify_is_transaction  = COALESCE(?, classify_is_transaction),
                    classify_reason          = COALESCE(?, classify_reason),
                    classify_confidence      = COALESCE(?, classify_confidence),
                    extract_prompt           = COALESCE(?, extract_prompt),
                    extract_raw_response     = COALESCE(?, extract_raw_response),
                    account_resolution       = COALESCE(?, account_resolution),
                    extracted_amount         = COALESCE(?, extracted_amount),
                    extracted_date           = COALESCE(?, extracted_date),
                    extracted_payment_type   = COALESCE(?, extracted_payment_type),
                    extracted_payee          = COALESCE(?, extracted_payee),
                    extracted_note           = COALESCE(?, extracted_note),
                    extracted_account_name   = COALESCE(?, extracted_account_name),
                    extracted_account_id     = COALESCE(?, extracted_account_id),
                    extracted_category_name  = COALESCE(?, extracted_category_name),
                    extracted_category_id    = COALESCE(?, extracted_category_id),
                    extracted_skip_reason    = COALESCE(?, extracted_skip_reason),
                    validation_result        = COALESCE(?, validation_result),
                    wallet_record_id         = COALESCE(?, wallet_record_id),
                    error_message            = COALESCE(?, error_message),
                    decision_notes           = COALESCE(?, decision_notes),
                    updated_at               = ?
                WHERE email_id = ?
            """, (
                request_status.value if request_status else None,
                classification_status.value if classification_status else None,
                classification_method.value if classification_method else None,
                heuristic_rule,
                extraction_status.value if extraction_status else None,
                classify_prompt,
                classify_raw_response,
                classify_int,
                classify_reason,
                classify_confidence,
                extract_prompt,
                extract_raw_response,
                account_resolution,
                extracted_amount,
                extracted_date,
                extracted_payment_type,
                extracted_payee,
                extracted_note,
                extracted_account_name,
                extracted_account_id,
                extracted_category_name,
                extracted_category_id,
                extracted_skip_reason,
                validation_result,
                wallet_record_id,
                error_message,
                decision_notes,
                now, email_id,
            ))
            conn.commit()

    def increment_retry(self, email_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE processed_emails SET retry_count = retry_count + 1 WHERE email_id = ?",
                (email_id,)
            )
            conn.commit()

    def get_retry_count(self, email_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT retry_count FROM processed_emails WHERE email_id = ?", (email_id,))
            result = cursor.fetchone()
            return result[0] if result else 0

    def is_processed(self, email_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM processed_emails WHERE email_id = ?", (email_id,))
            return cursor.fetchone() is not None

    def should_skip(self, email_id: str, max_retries: int) -> bool:
        """True if email is complete or has exceeded max retries."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT request_status, retry_count FROM processed_emails WHERE email_id = ?",
                (email_id,)
            )
            row = cursor.fetchone()
        if row is None:
            return False
        status, retries = row
        if status == RequestStatus.COMPLETED.value:
            return True
        if status == RequestStatus.FAILED.value and retries >= max_retries:
            return True
        return False

    def get_email_status(self, email_id: str) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM processed_emails WHERE email_id = ?", (email_id,))
            result = cursor.fetchone()
            return dict(result) if result else None

    def get_emails_by_status(self,
                              request_status: RequestStatus = None,
                              classification_status: ClassificationStatus = None,
                              extraction_status: ExtractionStatus = None,
                              limit: int = 50) -> List[Dict]:
        conditions, params = [], []
        if request_status:
            conditions.append("request_status = ?")
            params.append(request_status.value)
        if classification_status:
            conditions.append("classification_status = ?")
            params.append(classification_status.value)
        if extraction_status:
            conditions.append("extraction_status = ?")
            params.append(extraction_status.value)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT * FROM processed_emails {where} ORDER BY created_at DESC LIMIT ?",
                params
            )
            return [dict(row) for row in cursor.fetchall()]

    # ── Caches ────────────────────────────────────────────────────────────────

    def cache_accounts(self, accounts: List[Dict]):
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM account_cache")
            for acc in accounts:
                conn.execute(
                    "INSERT INTO account_cache (account_id, account_name, cached_at) VALUES (?, ?, ?)",
                    (acc["id"], acc["name"], now)
                )
            conn.commit()

    def cache_categories(self, categories: List[Dict]):
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM category_cache")
            for cat in categories:
                conn.execute(
                    "INSERT INTO category_cache (category_id, category_name, cached_at) VALUES (?, ?, ?)",
                    (cat["id"], cat["name"], now)
                )
            conn.commit()

    def cache_labels(self, labels: List[Dict]):
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("DELETE FROM label_cache")
                for lbl in labels:
                    conn.execute(
                        "INSERT INTO label_cache (label_id, label_name, cached_at) VALUES (?, ?, ?)",
                        (lbl["id"], lbl["name"], now)
                    )
                conn.commit()
            except Exception as e:
                logger.warning(f"Label cache update failed: {e}")

    def get_account_map(self) -> Dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT account_name, account_id FROM account_cache")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_category_map(self) -> Dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category_name, category_id FROM category_cache")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_label_map(self) -> Dict[str, str]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT label_name, label_id FROM label_cache")
                return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception:
            return {}

    # ── LLM interactions ──────────────────────────────────────────────────────

    def record_llm_interaction(self, email_id: str, provider: str, model: str,
                               system_prompt: str, user_prompt: str,
                               raw_response: str, parsed_output: str = None,
                               parsing_error: str = None, success: bool = False,
                               interaction_type: str = "extract",
                               run_id: str = None):
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO llm_interactions
                (email_id, run_id, interaction_type, provider, model, system_prompt,
                 user_prompt, raw_response, parsed_output, parsing_error, success, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (email_id, run_id, interaction_type, provider, model,
                  system_prompt, user_prompt, raw_response, parsed_output,
                  parsing_error, success, now))
            conn.commit()

    def get_llm_interactions(self, email_id: str = None, provider: str = None,
                              interaction_type: str = None, success: bool = None,
                              limit: int = 50) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM llm_interactions WHERE 1=1"
            params = []
            if email_id:
                query += " AND email_id = ?"
                params.append(email_id)
            if provider:
                query += " AND provider = ?"
                params.append(provider)
            if interaction_type:
                query += " AND interaction_type = ?"
                params.append(interaction_type)
            if success is not None:
                query += " AND success = ?"
                params.append(1 if success else 0)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # ── Reset helpers ─────────────────────────────────────────────────────────

    def reset_mock_posted(self) -> int:
        """Reset Phase 1/2 mock-posted records so Phase 3 will actually post them."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE processed_emails
                SET request_status    = 'failed',
                    extraction_status = 'extracted',
                    retry_count       = 0,
                    wallet_record_id  = NULL,
                    updated_at        = ?
                WHERE extraction_status = 'posted'
                AND (decision_notes LIKE '[Phase 1]%' OR decision_notes LIKE '[Phase 2]%')
            """, (datetime.utcnow().isoformat(),))
            count = cursor.rowcount
            conn.commit()
        logger.info(f"Reset {count} mock-posted records for Phase 3 reprocessing")
        return count

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> Dict:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT request_status, COUNT(*) FROM processed_emails GROUP BY request_status")
            request_stats = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute("SELECT classification_status, COUNT(*) FROM processed_emails GROUP BY classification_status")
            classification_stats = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute("SELECT extraction_status, COUNT(*) FROM processed_emails GROUP BY extraction_status")
            extraction_stats = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute("SELECT classification_method, COUNT(*) FROM processed_emails GROUP BY classification_method")
            method_stats = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "request_status":      request_stats,
            "classification_status": classification_stats,
            "extraction_status":   extraction_stats,
            "classification_method": method_stats,
        }

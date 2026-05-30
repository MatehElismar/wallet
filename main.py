#!/usr/bin/env python3
"""
Wallet Email-to-Record Automation System
Main orchestrator for the email processing pipeline.
"""

import logging
import sys
from typing import List, Dict
from email_parser import EmailParser
from email_client import create_email_client
from llm_client import create_llm_client
from wallet_client import WalletAPIClient
from validator import RecordValidator
from state_store import StateStore, ProcessingStatus
from dead_letter import DeadLetterQueue
from multi_account import MultiAccountEmailClient, MultiAccountConfig
import config

# Configure logging
logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EmailTxnPipeline:
    """Main orchestrator for email → Wallet record processing."""

    def __init__(self, phase: int = 1, multi_account: bool = False):
        self.phase = phase
        self.multi_account_mode = multi_account
        config.validate_config_for_phase(phase)

        if multi_account:
            self.multi_account_client = MultiAccountEmailClient()
            self.email_client = None
        else:
            self.email_client = create_email_client()
            self.multi_account_client = None

        self.email_parser = EmailParser()
        self.state_store = StateStore()
        self.dead_letter = DeadLetterQueue()

        # LLM client available from Phase 1+ (for testing with mocks)
        self.llm_client = create_llm_client()

        if self.phase >= 3:
            self.wallet_client = WalletAPIClient()
        else:
            self.wallet_client = None

        self.validator = None
        self.account_map = {}
        self.category_map = {}

        logger.info(f"Pipeline initialized for Phase {phase}")

    def bootstrap(self) -> bool:
        """
        Bootstrap: fetch accounts and categories from Wallet API.
        In Phase 1, use mock data.
        """
        if self.phase < 3:
            # Mock data for Phase 1-2
            self.account_map = {
                "Checking": "123e4567-e89b-12d3-a456-426614174000",
                "Savings": "223e4567-e89b-12d3-a456-426614174001",
                "Credit Card": "323e4567-e89b-12d3-a456-426614174002",
            }
            self.category_map = {
                "Food & Drinks": "423e4567-e89b-12d3-a456-426614174100",
                "Transport": "423e4567-e89b-12d3-a456-426614174101",
                "Entertainment": "423e4567-e89b-12d3-a456-426614174102",
                "Shopping": "423e4567-e89b-12d3-a456-426614174103",
                "Health": "423e4567-e89b-12d3-a456-426614174104",
                "Subscriptions": "423e4567-e89b-12d3-a456-426614174105",
            }
            logger.info("Loaded mock account and category maps")
        else:
            # Real API call for Phase 3+
            try:
                accounts = self.wallet_client.get_accounts()
                categories = self.wallet_client.get_categories()

                self.account_map = {acc["name"]: acc["id"] for acc in accounts}
                self.category_map = {cat["name"]: cat["id"] for cat in categories}

                self.state_store.cache_accounts(accounts)
                self.state_store.cache_categories(categories)

                logger.info(f"Bootstrapped {len(self.account_map)} accounts, {len(self.category_map)} categories")
                return True
            except Exception as e:
                logger.error(f"Bootstrap failed: {e}")
                return False

        self.validator = RecordValidator(self.account_map, self.category_map)
        return True

    def process_emails(self) -> int:
        """
        Main processing loop:
        1. Fetch new emails
        2. Send each to LLM
        3. Validate output
        4. Batch and post to Wallet API
        """
        if self.multi_account_mode:
            return self._process_multi_account()
        else:
            return self._process_single_account()

    def _process_multi_account(self) -> int:
        """Process emails from multiple accounts."""
        try:
            all_emails = self.multi_account_client.fetch_all_emails()
            total_emails = sum(len(emails) for emails in all_emails.values())

            if total_emails == 0:
                logger.info("No new emails from any account")
                return 0

            total_processed = 0
            for account_name, emails in all_emails.items():
                logger.info(f"Processing {len(emails)} emails from {account_name}")
                processed = self._process_email_batch(emails, account_name)
                total_processed += processed

            self._print_stats()
            return total_processed

        except Exception as e:
            logger.error(f"Multi-account pipeline error: {e}", exc_info=True)
            return 0

    def _process_single_account(self) -> int:
        """Process emails from single account."""
        try:
            emails = self.email_client.fetch_new_emails()
            if not emails:
                logger.info("No new emails to process")
                return 0

            processed = self._process_email_batch(emails, "default")
            self._print_stats()
            return processed

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            return 0

    def _process_email_batch(self, emails: list, account_name: str = "default") -> int:
        """Process a batch of emails from an account."""
        records_to_post = []

        for email_meta in emails:
            # Skip if already processed
            if self.state_store.is_processed(email_meta.email_id):
                logger.debug(f"Email {email_meta.email_id} already processed, skipping")
                continue

            # Record the email as pending
            self.state_store.record_email(
                email_meta.email_id,
                email_meta.subject,
                email_meta.sender,
                email_meta.received_date.isoformat(),
            )

            # Quick heuristic: is this likely a transaction?
            if not self.email_parser.is_likely_transaction(email_meta.subject, email_meta.body):
                logger.debug(f"Email {email_meta.email_id} flagged as non-transaction")
                self.state_store.update_status(
                    email_meta.email_id,
                    ProcessingStatus.LLM_SKIP,
                )
                self.dead_letter.add(
                    email_meta.email_id,
                    email_meta.subject,
                    email_meta.sender,
                    "Flagged as likely non-transaction",
                )
                continue

            # Send to LLM
            self.state_store.update_status(email_meta.email_id, ProcessingStatus.LLM_PROCESSING)

            accounts = list(self.account_map.keys())
            accounts = [{"id": self.account_map[name], "name": name} for name in accounts]
            categories = list(self.category_map.keys())
            categories = [{"id": self.category_map[name], "name": name} for name in categories]

            email_text = self.email_parser.prepare_for_llm(email_meta)

            llm_output = self.llm_client.extract(email_text, accounts, categories)

            if not llm_output:
                logger.warning(f"LLM extraction failed for {email_meta.email_id}")
                self.state_store.update_status(
                    email_meta.email_id,
                    ProcessingStatus.LLM_ERROR,
                    error_message="Failed to parse LLM response",
                )
                self.state_store.increment_retry(email_meta.email_id)
                continue

            # Store LLM output
            self.state_store.update_status(
                email_meta.email_id,
                ProcessingStatus.API_PENDING,
                llm_output=str(llm_output),
            )

            # Validate
            is_valid, error = self.validator.validate_record(llm_output)

            if not is_valid:
                logger.warning(f"Validation failed for {email_meta.email_id}: {error}")
                self.state_store.update_status(
                    email_meta.email_id,
                    ProcessingStatus.VALIDATION_ERROR,
                    error_message=error,
                )
                self.dead_letter.add(
                    email_meta.email_id,
                    email_meta.subject,
                    email_meta.sender,
                    f"Validation error: {error}",
                    llm_output,
                )
                continue

            # Normalize and add to batch
            normalized = self.validator.normalize_record(llm_output)
            records_to_post.append({
                "email_id": email_meta.email_id,
                "record": normalized,
            })

            # If batch is full, post it
            if len(records_to_post) >= config.MAX_BATCH_SIZE:
                self._post_batch(records_to_post)
                records_to_post = []

        # Post remaining records
        if records_to_post:
            self._post_batch(records_to_post)

        return len(records_to_post)

    def _post_batch(self, records_to_post: List[Dict]):
        """Post a batch of records to Wallet API."""
        if not records_to_post:
            return

        records = [r["record"] for r in records_to_post]

        if self.phase < 3:
            logger.info(f"[PHASE {self.phase}] Would post {len(records)} records to Wallet API:")
            for email_data in records_to_post:
                record = email_data["record"]
                logger.info(
                    f"  - {record['counterParty']} {record['amount']} "
                    f"({record['paymentType']}) → {record['accountId']}"
                )
            # Mark as success in Phase 1-2
            for email_data in records_to_post:
                self.state_store.update_status(
                    email_data["email_id"],
                    ProcessingStatus.API_SUCCESS,
                )
        else:
            # Real API call
            status_code, results = self.wallet_client.post_records(
                records,
                dry_run=config.PIPELINE_DRY_RUN,
            )

            for i, email_data in enumerate(records_to_post):
                email_id = email_data["email_id"]
                result = results[i] if i < len(results) else {}

                if result.get("status") == "success":
                    wallet_record_id = result.get("id")
                    self.state_store.update_status(
                        email_id,
                        ProcessingStatus.API_SUCCESS,
                        wallet_record_id=wallet_record_id,
                    )
                elif result.get("errorType") == "server_error":
                    self.state_store.update_status(
                        email_id,
                        ProcessingStatus.API_SERVER_ERROR,
                        error_message=result.get("message"),
                    )
                    self.state_store.increment_retry(email_id)
                else:
                    self.state_store.update_status(
                        email_id,
                        ProcessingStatus.API_CLIENT_ERROR,
                        error_message=result.get("message"),
                    )
                    self.dead_letter.add(
                        email_id,
                        records_to_post[i]["record"].get("note", ""),
                        records_to_post[i]["record"].get("counterParty", ""),
                        result.get("message", "API error"),
                    )

    def _print_stats(self):
        """Print processing statistics."""
        stats = self.state_store.stats()
        dlq_stats = self.dead_letter.stats()

        logger.info("=== Pipeline Stats ===")
        for status, count in stats.items():
            logger.info(f"  {status}: {count}")
        logger.info(f"Dead Letter Queue: {dlq_stats['total']} items")
        if dlq_stats['by_reason']:
            for reason, count in dlq_stats['by_reason'].items():
                logger.info(f"    {reason}: {count}")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Wallet Email-to-Record Automation")
    parser.add_argument("--phase", type=int, default=1, choices=[1, 2, 3, 4],
                        help="Implementation phase (1-4)")
    parser.add_argument("--bootstrap", action="store_true", help="Run bootstrap only")
    parser.add_argument("--multi-account", action="store_true",
                        help="Enable multi-account mode (read from email_accounts.json)")
    parser.add_argument("--show-accounts", action="store_true",
                        help="Show configured accounts and exit")
    args = parser.parse_args()

    if args.show_accounts:
        config_obj = MultiAccountConfig()
        stats = {"accounts": config_obj.accounts}
        import json
        print(json.dumps([acc.to_dict() for acc in config_obj.accounts], indent=2))
        return

    mode = "Multi-Account" if args.multi_account else "Single-Account"
    logger.info(f"Starting Wallet Email Sync Pipeline (Phase {args.phase}, {mode} Mode)")

    pipeline = EmailTxnPipeline(phase=args.phase, multi_account=args.multi_account)

    if not pipeline.bootstrap():
        logger.error("Bootstrap failed")
        sys.exit(1)

    if args.bootstrap:
        logger.info("Bootstrap complete")
        return

    emails_processed = pipeline.process_emails()
    logger.info(f"Pipeline run complete. Processed {emails_processed} emails")


if __name__ == "__main__":
    main()

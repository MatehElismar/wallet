#!/usr/bin/env python3
"""
Wallet Email-to-Record Automation System
Main orchestrator for the email processing pipeline.
"""

import json
import logging
import sys
import uuid
from typing import List, Dict

from email_parser import EmailParser
from email_client import MockEmailClient
from llm_client import create_llm_client
from wallet_client import WalletAPIClient
from validator import RecordValidator
from state_store import (
    StateStore,
    RequestStatus,
    ClassificationStatus,
    ClassificationMethod,
    ExtractionStatus,
)
from account_resolver import AccountResolver
from dead_letter import DeadLetterQueue
from multi_account import MultiAccountEmailClient, MultiAccountConfig
import config

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EmailTxnPipeline:
    """Main orchestrator for email → Wallet record processing."""

    def __init__(self, phase: int = 1, days_back: int = 0):
        self.phase = phase
        self.days_back = days_back
        config.validate_config_for_phase(phase)

        # Phase 1 uses mock emails; Phase 2+ reads from email_accounts.json
        self.email_client = MultiAccountEmailClient() if phase >= 2 else None

        self.email_parser = EmailParser()
        self.state_store = StateStore()
        self.dead_letter = DeadLetterQueue()
        self.llm_client = create_llm_client()

        self.wallet_client = WalletAPIClient() if self.phase >= 3 else None

        self.validator = None
        self.account_map = {}
        self.category_map = {}
        self.auto_entry_label_id = None
        self.account_resolver = None
        self._all_accounts = []   # full account objects for LLM prompt
        self._all_categories = [] # full category objects for LLM prompt

        logger.info(f"Pipeline initialized for Phase {phase}")

    def bootstrap(self) -> bool:
        """Fetch accounts and categories from Wallet API (or use mock data for Phase 1-2)."""
        if self.phase < 3:
            self.account_map = {
                "Checking":    "123e4567-e89b-12d3-a456-426614174000",
                "Savings":     "223e4567-e89b-12d3-a456-426614174001",
                "Credit Card": "323e4567-e89b-12d3-a456-426614174002",
            }
            self.category_map = {
                "Food & Drinks":  "423e4567-e89b-12d3-a456-426614174100",
                "Transport":      "423e4567-e89b-12d3-a456-426614174101",
                "Entertainment":  "423e4567-e89b-12d3-a456-426614174102",
                "Shopping":       "423e4567-e89b-12d3-a456-426614174103",
                "Health":         "423e4567-e89b-12d3-a456-426614174104",
                "Subscriptions":  "423e4567-e89b-12d3-a456-426614174105",
            }
            logger.info("Loaded mock account and category maps")
        else:
            try:
                if not self.wallet_client.check_api_health():
                    logger.error("Wallet API health check failed — check token and connectivity")
                    return False

                accounts = self.wallet_client.get_accounts()
                categories = self.wallet_client.get_categories()
                labels = self.wallet_client.get_labels()

                # Only expose active (non-archived) accounts and categories to the LLM
                active_accounts = [a for a in accounts if not a.get("archived")]
                active_categories = [c for c in categories if not c.get("archived")]

                self.account_map = {acc["name"]: acc["id"] for acc in active_accounts}
                self.category_map = {cat["name"]: cat["id"] for cat in active_categories}
                self._all_accounts = active_accounts
                self._all_categories = active_categories

                self.account_resolver = AccountResolver(active_accounts)

                self.state_store.cache_accounts(active_accounts)
                self.state_store.cache_categories(active_categories)
                self.state_store.cache_labels(labels)

                # "Imported" label tags every record created by this pipeline.
                imported_label = next(
                    (l for l in labels if l.get("name", "").strip().lower() == "imported"),
                    None
                )
                self.auto_entry_label_id = imported_label["id"] if imported_label else None
                if self.auto_entry_label_id:
                    logger.info(f"Imported label: {imported_label['name']!r} → {self.auto_entry_label_id}")
                else:
                    logger.warning("Label 'Imported' not found in Wallet — records will be posted without a sync label.")

                logger.info(
                    f"Bootstrapped {len(self.account_map)} accounts, "
                    f"{len(self.category_map)} categories, {len(labels)} labels"
                )
            except Exception as e:
                logger.error(f"Bootstrap failed: {e}")
                return False

        self.validator = RecordValidator(self.account_map, self.category_map)
        return True

    def process_emails(self) -> int:
        """Fetch emails from email_accounts.json and run the pipeline."""
        run_id = str(uuid.uuid4())
        run_stats = {"fetched": 0, "classified": 0, "extracted": 0, "posted": 0, "errors": 0}

        if self.phase == 1:
            emails = MockEmailClient().fetch_new_emails()
            self.state_store.create_run(run_id, self.phase, ["mock"])
            run_stats["fetched"] = len(emails)
            count = self._process_email_batch(emails, "mock", run_id=run_id, run_stats=run_stats)
            self.state_store.complete_run(run_id, run_stats)
            self._print_stats()
            return count

        try:
            all_emails = self.email_client.fetch_all_emails(days_back=self.days_back)
            inbox_names = list(all_emails.keys())
            total = sum(len(v) for v in all_emails.values())

            self.state_store.create_run(run_id, self.phase, inbox_names)
            run_stats["fetched"] = total

            if total == 0:
                logger.info("No new emails")
                self.state_store.complete_run(run_id, run_stats)
                return 0

            count = 0
            for account_name, emails in all_emails.items():
                if emails:
                    logger.info(f"Processing {len(emails)} emails from {account_name}")
                count += self._process_email_batch(
                    emails, account_name, run_id=run_id, run_stats=run_stats
                )

            self.state_store.complete_run(run_id, run_stats)
            self._print_stats()
            return count
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            self.state_store.complete_run(run_id, run_stats)
            return 0

    def _process_email_batch(self, emails: list, account_name: str = "default",
                             run_id: str = None, run_stats: Dict = None) -> int:
        """
        Classify-first pipeline:
          1. Heuristic classify
          2. LLM classify  (if uncertain)
          3. LLM extract   (confirmed transactions only)
          4. Validate
          5. Post to Wallet API
        """
        records_to_post = []
        posted_count = 0
        llm_model = getattr(self.llm_client, "model", "unknown")
        # Use full account/category objects so LLM prompt shows type and currency
        accounts = self._all_accounts or [{"id": v, "name": k} for k, v in self.account_map.items()]
        categories = self._all_categories or [{"id": v, "name": k} for k, v in self.category_map.items()]

        for email_meta in emails:
            email_id = email_meta.email_id

            # ── Guard: skip completed or exhausted emails ─────────────
            if self.state_store.should_skip(email_id, config.RETRY_MAX_ATTEMPTS):
                logger.debug(f"Skipping {email_id}: completed or max retries reached")
                continue

            if not self.state_store.is_processed(email_id):
                self.state_store.record_email(
                    email_id,
                    email_meta.subject,
                    email_meta.sender,
                    email_meta.received_date.isoformat(),
                    email_body=email_meta.body,
                    run_id=run_id,
                    inbox_account=account_name,
                )

            subject = email_meta.subject or ""
            body = email_meta.body or ""

            # ── Step 1: Heuristic classification ──────────────────────
            heuristic_result, heuristic_rule = self.email_parser.classify_by_heuristic(subject, body)

            if heuristic_result == "not_transaction":
                logger.debug(f"Heuristic rejected {email_id}: {heuristic_rule}")
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.COMPLETED,
                    classification_status=ClassificationStatus.NOT_TRANSACTION,
                    classification_method=ClassificationMethod.HEURISTIC,
                    heuristic_rule=heuristic_rule,
                    extraction_status=ExtractionStatus.NOT_ATTEMPTED,
                    decision_notes=f"Heuristic: {heuristic_rule}",
                )
                continue

            email_text = self.email_parser.prepare_for_llm(email_meta)

            # ── Step 2: LLM classify (only when heuristic is uncertain) ──
            if heuristic_result == "uncertain":
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.PROCESSING,
                    decision_notes="Heuristic uncertain — sending to LLM classifier",
                )

                classify_response = self.llm_client.classify(email_text)

                if classify_response is None:
                    logger.warning(f"LLM classify API error for {email_id}")
                    self.state_store.update_status(
                        email_id,
                        request_status=RequestStatus.FAILED,
                        extraction_status=ExtractionStatus.ERROR,
                        error_message="LLM classification API error (no response)",
                        decision_notes="LLM classify call returned None",
                    )
                    self.state_store.increment_retry(email_id)
                    self.dead_letter.add(
                        email_id, email_meta.subject, email_meta.sender,
                        "LLM classify API error",
                    )
                    continue

                cls_output = classify_response.get("output") or {}
                cls_success = classify_response.get("success", False)

                cls_sys = classify_response.get("system_prompt", "")
                cls_usr = classify_response.get("user_prompt", "")
                cls_raw = classify_response.get("raw_response", "")

                self.state_store.record_llm_interaction(
                    email_id=email_id,
                    provider=config.LLM_PROVIDER,
                    model=llm_model,
                    system_prompt=cls_sys,
                    user_prompt=cls_usr,
                    raw_response=cls_raw,
                    parsed_output=json.dumps(cls_output) if cls_output else None,
                    parsing_error=classify_response.get("parsing_error"),
                    success=cls_success,
                    interaction_type="classify",
                    run_id=run_id,
                )

                # Always store classify prompt + raw response
                self.state_store.update_status(
                    email_id,
                    classify_prompt=f"SYSTEM:\n{cls_sys}\n\nUSER:\n{cls_usr}",
                    classify_raw_response=cls_raw,
                )

                if not cls_success or not cls_output:
                    parse_err = classify_response.get("parsing_error", "parse error")
                    logger.warning(f"LLM classify parse failed for {email_id}: {parse_err}")
                    self.state_store.update_status(
                        email_id,
                        request_status=RequestStatus.FAILED,
                        extraction_status=ExtractionStatus.ERROR,
                        error_message=parse_err,
                        decision_notes="LLM classify response could not be parsed",
                    )
                    self.state_store.increment_retry(email_id)
                    if run_stats: run_stats["errors"] += 1
                    self.dead_letter.add(
                        email_id, email_meta.subject, email_meta.sender,
                        f"LLM classify parse error: {parse_err}",
                    )
                    continue

                is_txn = cls_output.get("is_transaction", False)
                reason = cls_output.get("reason", "")
                confidence = cls_output.get("confidence", "")

                # Store classify output fields
                self.state_store.update_status(
                    email_id,
                    classify_is_transaction=is_txn,
                    classify_reason=reason,
                    classify_confidence=confidence,
                )

                if not is_txn:
                    logger.debug(f"LLM classified {email_id} as not_transaction: {reason}")
                    self.state_store.update_status(
                        email_id,
                        request_status=RequestStatus.COMPLETED,
                        classification_status=ClassificationStatus.NOT_TRANSACTION,
                        classification_method=ClassificationMethod.LLM,
                        extraction_status=ExtractionStatus.NOT_ATTEMPTED,
                        decision_notes=f"LLM classify ({confidence}): {reason}",
                    )
                    if run_stats: run_stats["classified"] += 1
                    continue

                # LLM confirmed: is a transaction
                self.state_store.update_status(
                    email_id,
                    classification_status=ClassificationStatus.TRANSACTION,
                    classification_method=ClassificationMethod.LLM,
                    decision_notes=f"LLM classify ({confidence}): {reason}",
                )
                if run_stats: run_stats["classified"] += 1

            else:
                # heuristic_result == "transaction" — strong positive signal
                logger.debug(f"Heuristic confirmed transaction {email_id}: {heuristic_rule}")
                self.state_store.update_status(
                    email_id,
                    classification_status=ClassificationStatus.TRANSACTION,
                    classification_method=ClassificationMethod.HEURISTIC,
                    heuristic_rule=heuristic_rule,
                    decision_notes=f"Heuristic positive: {heuristic_rule}",
                )

            # ── Step 3: Account pre-resolution ───────────────────────────
            resolved_account = None
            if self.account_resolver:
                resolved_account = self.account_resolver.resolve(
                    subject=subject,
                    sender=email_meta.sender or "",
                    body=body,
                    bank_hint=getattr(email_meta, "bank_hint", None),
                )
                conf = resolved_account.get("confidence", "none")
                if conf == "high":
                    logger.debug(
                        f"Account resolved [{resolved_account['method']}]: "
                        f"{resolved_account.get('account_name')!r}"
                    )
                elif conf in ("medium", "low"):
                    n = len(resolved_account.get("candidates", [resolved_account]))
                    logger.debug(f"Account narrowed [{resolved_account['method']}]: {n} candidate(s)")

            # ── Step 4: LLM extraction ────────────────────────────────
            self.state_store.update_status(
                email_id,
                request_status=RequestStatus.PROCESSING,
                extraction_status=ExtractionStatus.PENDING,
            )

            all_cats = self._all_categories or categories
            system_prompt = self.llm_client.build_system_prompt(
                accounts, all_cats, resolved_account=resolved_account
            )
            user_prompt = self.llm_client.build_user_prompt(email_text)
            full_prompt = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}"

            llm_response = self.llm_client.extract(
                email_text, accounts, all_cats, resolved_account=resolved_account
            )

            if llm_response is None:
                logger.warning(f"LLM extraction API error for {email_id}")
                self.state_store.record_llm_interaction(
                    email_id=email_id, provider=config.LLM_PROVIDER, model=llm_model,
                    system_prompt=system_prompt, user_prompt=user_prompt,
                    raw_response="", success=False, interaction_type="extract", run_id=run_id,
                )
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.FAILED,
                    extraction_status=ExtractionStatus.ERROR,
                    extract_prompt=full_prompt,
                    error_message="LLM extraction API error (no response)",
                    decision_notes="LLM extract returned None",
                )
                self.state_store.increment_retry(email_id)
                if run_stats: run_stats["errors"] += 1
                self.dead_letter.add(email_id, email_meta.subject, email_meta.sender,
                                     "LLM extraction API error")
                continue

            extract_output = llm_response.get("output")
            extract_success = llm_response.get("success", False)
            extract_system = llm_response.get("system_prompt", system_prompt)
            extract_user = llm_response.get("user_prompt", user_prompt)
            extract_raw = llm_response.get("raw_response", "")
            parsing_error = llm_response.get("parsing_error")
            extract_full_prompt = f"SYSTEM:\n{extract_system}\n\nUSER:\n{extract_user}"

            self.state_store.record_llm_interaction(
                email_id=email_id, provider=config.LLM_PROVIDER, model=llm_model,
                system_prompt=extract_system, user_prompt=extract_user,
                raw_response=extract_raw,
                parsed_output=json.dumps(extract_output) if extract_output else None,
                parsing_error=parsing_error, success=extract_success,
                interaction_type="extract", run_id=run_id,
            )

            # Always store extract prompt + raw response
            self.state_store.update_status(
                email_id,
                extract_prompt=extract_full_prompt,
                extract_raw_response=extract_raw,
            )

            if not extract_success or parsing_error:
                logger.warning(f"LLM extraction parse failed for {email_id}: {parsing_error}")
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.FAILED,
                    extraction_status=ExtractionStatus.ERROR,
                    error_message=parsing_error or "LLM extraction parse error",
                    decision_notes=f"LLM extract JSON parse failed: {parsing_error}",
                )
                self.state_store.increment_retry(email_id)
                if run_stats: run_stats["errors"] += 1
                self.dead_letter.add(email_id, email_meta.subject, email_meta.sender,
                                     f"LLM parse error: {parsing_error}")
                continue

            # ── Step 4: Validate ──────────────────────────────────────

            # If the LLM extractor signals it's not a transaction, accept that signal
            if extract_output.get("skipReason"):
                skip_reason = extract_output["skipReason"]
                logger.debug(f"LLM extractor returned skipReason for {email_id}: {skip_reason}")
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.COMPLETED,
                    classification_status=ClassificationStatus.NOT_TRANSACTION,
                    extraction_status=ExtractionStatus.NOT_ATTEMPTED,
                    extracted_skip_reason=skip_reason,
                    decision_notes=f"LLM extractor skipReason: {skip_reason}",
                )
                continue

            # Store extracted fields as flat columns (regardless of validation outcome)
            self.state_store.update_status(
                email_id,
                extracted_amount=extract_output.get("amount"),
                extracted_date=extract_output.get("recordDate"),
                extracted_payment_type=extract_output.get("paymentType"),
                extracted_payee=extract_output.get("payee"),
                extracted_note=extract_output.get("note"),
                extracted_account_name=extract_output.get("accountName"),
                extracted_category_name=extract_output.get("categoryName"),
                extraction_status=ExtractionStatus.EXTRACTED,
                decision_notes=(
                    f"Extracted: {extract_output.get('payee') or extract_output.get('note', '?')} "
                    f"{extract_output.get('amount', '?')}"
                ),
            )

            is_valid, error = self.validator.validate_record(extract_output)

            if not is_valid:
                logger.warning(f"Validation failed for {email_id}: {error}")
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.COMPLETED,
                    extraction_status=ExtractionStatus.INVALID,
                    validation_result=error,
                    decision_notes=f"Validation failed: {error}",
                )
                if run_stats: run_stats["errors"] += 1
                self.dead_letter.add(
                    email_id, email_meta.subject, email_meta.sender,
                    f"Validation: {error}", extract_output,
                )
                continue

            if run_stats: run_stats["extracted"] += 1

            # ── Step 5: Normalize and batch ───────────────────────────
            label_ids = [self.auto_entry_label_id] if self.auto_entry_label_id else []
            normalized = self.validator.normalize_record(extract_output, label_ids=label_ids)

            # Store resolved account/category IDs
            self.state_store.update_status(
                email_id,
                extracted_account_id=normalized.get("accountId"),
                extracted_category_id=normalized.get("categoryId"),
                account_resolution=resolved_account.get("method") if resolved_account else None,
            )

            records_to_post.append({"email_id": email_id, "record": normalized})

            if len(records_to_post) >= config.MAX_BATCH_SIZE:
                posted_count += self._post_batch(records_to_post)
                records_to_post = []

        if records_to_post:
            posted_count += self._post_batch(records_to_post)

        return posted_count

    def _post_batch(self, records_to_post: List[Dict]) -> int:
        """Post a batch of records to Wallet API. Returns number successfully posted."""
        if not records_to_post:
            return 0

        records = [r["record"] for r in records_to_post]

        if self.phase < 3:
            logger.info(f"[Phase {self.phase}] Would post {len(records)} records:")
            for item in records_to_post:
                rec = item["record"]
                logger.info(
                    f"  {rec.get('amount', '?')} "
                    f"({rec.get('paymentType', '?')}) → {rec.get('accountId', '?')}"
                )
            for item in records_to_post:
                self.state_store.update_status(
                    item["email_id"],
                    request_status=RequestStatus.COMPLETED,
                    extraction_status=ExtractionStatus.POSTED,
                    decision_notes=f"[Phase {self.phase}] Mock post successful",
                )
            return len(records_to_post)

        status_code, results = self.wallet_client.post_records(
            records, dry_run=config.PIPELINE_DRY_RUN
        )

        posted = 0

        # 200/201 with no per-record results = treat all as success
        if status_code in (200, 201) and not results:
            logger.info(f"Wallet API accepted all {len(records_to_post)} records")
            for item in records_to_post:
                self.state_store.update_status(
                    item["email_id"],
                    request_status=RequestStatus.COMPLETED,
                    extraction_status=ExtractionStatus.POSTED,
                    decision_notes="Successfully posted to Wallet API",
                )
            return len(records_to_post)

        for i, item in enumerate(records_to_post):
            email_id = item["email_id"]
            # Results array uses inputIndex, but position in array matches order
            result = results[i] if i < len(results) else {}

            # Support both dry-run format {"status": "success"} and
            # real API format {"success": true, "id": "uuid", "record": {...}}
            is_success = result.get("success") is True or result.get("status") == "success"
            record_id = result.get("id") or (result.get("record") or {}).get("id")

            if is_success:
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.COMPLETED,
                    extraction_status=ExtractionStatus.POSTED,
                    wallet_record_id=record_id,
                    decision_notes="Successfully posted to Wallet API",
                )
                posted += 1

            elif result.get("errorType") == "server_error":
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.FAILED,
                    extraction_status=ExtractionStatus.API_ERROR,
                    error_message=result.get("message"),
                    decision_notes=f"API server error: {result.get('message')}",
                )
                self.state_store.increment_retry(email_id)
                self.dead_letter.add(
                    email_id,
                    item["record"].get("note", ""),
                    item["record"].get("counterParty", ""),
                    f"API server error: {result.get('message')}",
                )

            else:
                self.state_store.update_status(
                    email_id,
                    request_status=RequestStatus.FAILED,
                    extraction_status=ExtractionStatus.API_ERROR,
                    error_message=result.get("message"),
                    decision_notes=f"API client error: {result.get('message')}",
                )
                self.dead_letter.add(
                    email_id,
                    item["record"].get("note", ""),
                    item["record"].get("counterParty", ""),
                    f"API client error: {result.get('message', 'unknown')}",
                )

        return posted

    def _print_stats(self):
        """Print pipeline statistics."""
        stats = self.state_store.stats()
        dlq_stats = self.dead_letter.stats()

        logger.info("=== Pipeline Stats ===")
        logger.info("  Request status:       " + str(stats.get("request_status", {})))
        logger.info("  Classification:       " + str(stats.get("classification_status", {})))
        logger.info("  Classification method:" + str(stats.get("classification_method", {})))
        logger.info("  Extraction:           " + str(stats.get("extraction_status", {})))
        logger.info(f"  Dead letter queue:    {dlq_stats['total']} items")
        if dlq_stats.get("by_reason"):
            for reason, count in dlq_stats["by_reason"].items():
                logger.info(f"    {reason}: {count}")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Wallet Email-to-Record Automation")
    parser.add_argument("--phase", type=int, default=1, choices=[1, 2, 3, 4])
    parser.add_argument("--bootstrap", action="store_true", help="Run bootstrap only")
    parser.add_argument("--show-accounts", action="store_true",
                        help="Print configured email accounts from email_accounts.json")
    parser.add_argument("--days", type=int, default=0,
                        help="Fetch emails from past N days (0=unread only)")
    args = parser.parse_args()

    if args.show_accounts:
        cfg_obj = MultiAccountConfig()
        print(json.dumps([acc.to_dict() for acc in cfg_obj.accounts], indent=2))
        return

    days_desc = f", last {args.days} days" if args.days > 0 else ", unread only"
    logger.info(f"Starting Wallet Email Sync (Phase {args.phase}{days_desc})")

    pipeline = EmailTxnPipeline(phase=args.phase, days_back=args.days)

    if not pipeline.bootstrap():
        logger.error("Bootstrap failed")
        sys.exit(1)

    if args.bootstrap:
        logger.info("Bootstrap complete")
        return

    count = pipeline.process_emails()
    logger.info(f"Pipeline complete. Posted {count} records.")


if __name__ == "__main__":
    main()

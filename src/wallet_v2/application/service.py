"""Review-first orchestration backed by the V2 persistence model."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wallet_v2.application.account_mapping import AccountMappingService
from wallet_v2.application.account_repair import AccountRepairService
from wallet_v2.application.contracts import (
    ExtractionResult,
    MailboxMessage,
    TransactionExtractor,
    WalletClient,
)
from wallet_v2.application.outbox import OutboxService
from wallet_v2.domain.notifications import NotificationIntent
from wallet_v2.domain.reference import canonical_external_reference
from wallet_v2.domain.enums import (
    AttemptStatus,
    AuditEventKind,
    CandidateStatus,
    DocumentKind,
    FinancialEventStatus,
    ImportCommandStatus,
    IntegrationMode,
    MailboxSourceStatus,
    ObservationStatus,
    ReconciliationMethod,
    ReconciliationOutcome,
    ReviewDecision,
    SourceMessageStatus,
    StatementStatus,
    WalletAttemptStatus,
)
from wallet_v2.persistence.models import (
    AuditEvent,
    BankStatement,
    BankStatementLine,
    ExecutionRun,
    FinancialAccount,
    FinancialEvent,
    ImportCommand,
    Inbox,
    InboxCursorHistory,
    MessageContentMetadata,
    ProcessingAttempt,
    ReviewDecisionRecord,
    ReviewTask,
    ReconciliationLink,
    SourceMessage,
    StatementReviewBatch,
    TransactionCandidate,
    TransactionObservation,
    WalletAttempt,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class WorkflowError(ValueError):
    """Raised when a requested workflow transition violates policy."""


class WalletWorkflow:
    """Coordinates persistence and adapter calls without hiding run identity."""

    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] = _utcnow,
        outbox_service: OutboxService | None = None,
    ):
        self.session = session
        self.now = now
        self._outbox = outbox_service or OutboxService(session)

    def start_run(
        self,
        *,
        mode: IntegrationMode,
        trigger: str,
        label: str,
        initiator: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ExecutionRun:
        if trigger not in {"manual", "scheduled", "test"}:
            raise WorkflowError("trigger must be manual, scheduled, or test")
        if not label.strip():
            raise WorkflowError("run label must not be blank")
        run = ExecutionRun(
            mode=mode,
            trigger=trigger,
            label=label.strip(),
            initiator=initiator,
            metadata_json=metadata,
            started_at=self.now(),
            outcome="running",
        )
        self.session.add(run)
        self.session.flush()
        self._audit(run, "execution_run", run.id, AuditEventKind.EXECUTION_RUN_STARTED)
        return run

    def finish_run(self, run: ExecutionRun, *, outcome: str, error: str | None = None) -> None:
        if outcome not in {"succeeded", "failed", "cancelled"}:
            raise WorkflowError("run outcome must be succeeded, failed, or cancelled")
        run.outcome = outcome
        run.finished_at = self.now()
        run.error_summary = error
        self._audit(
            run,
            "execution_run",
            run.id,
            AuditEventKind.EXECUTION_RUN_FINISHED,
            {"outcome": outcome},
        )
        if outcome == "failed":
            self._emit_notification(
                run,
                kind="run_failed",
                title="Execution Run Failed",
                body=f"Run outcome: failed" + (f" — {error}" if error else ""),
                entity_kind="execution_run",
                entity_id=run.id,
                metadata={"error": error} if error else None,
            )

    def ingest_and_extract(
        self,
        *,
        run: ExecutionRun,
        message: MailboxMessage,
        extractor: TransactionExtractor,
    ) -> tuple[SourceMessage, tuple[TransactionCandidate, ...], tuple[ReviewTask, ...]]:
        if run.mode == IntegrationMode.DISABLED:
            raise WorkflowError("disabled runs cannot ingest messages")
        source = self._record_source(run, message)
        if source.status == SourceMessageStatus.CONSUMED:
            return source, (), ()

        return self._extract_source(run=run, source=source, message=message, extractor=extractor)

    def reprocess(
        self,
        *,
        run: ExecutionRun,
        message: MailboxMessage,
        extractor: TransactionExtractor,
    ) -> tuple[SourceMessage, tuple[TransactionCandidate, ...], tuple[ReviewTask, ...]]:
        """Deliberately create a new append-only attempt for an existing message."""

        if run.mode == IntegrationMode.DISABLED:
            raise WorkflowError("disabled runs cannot reprocess messages")
        source = self._record_source(run, message)
        return self._extract_source(run=run, source=source, message=message, extractor=extractor)

    def _extract_source(
        self,
        *,
        run: ExecutionRun,
        source: SourceMessage,
        message: MailboxMessage,
        extractor: TransactionExtractor,
    ) -> tuple[SourceMessage, tuple[TransactionCandidate, ...], tuple[ReviewTask, ...]]:

        result = extractor.extract(message)
        attempt = self._record_attempt(run, source, result)
        if not result.is_transaction:
            source.status = SourceMessageStatus.CONSUMED
            self._advance_cursor(source)
            return source, (), ()
        if result.document_kind == DocumentKind.STATEMENT:
            self._record_statement(
                run=run,
                source=source,
                attempt=attempt,
                result=result,
            )
            source.status = SourceMessageStatus.CONSUMED
            self._advance_cursor(source)
            self.session.flush()
            return source, (), ()
        candidates: list[TransactionCandidate] = []
        tasks: list[ReviewTask] = []
        for source_item_index, transaction in enumerate(result.transactions, start=1):
            if transaction.amount_minor <= 0:
                raise WorkflowError("transaction amount must be strictly positive")
            if len(transaction.currency) != 3 or not transaction.currency.isupper():
                raise WorkflowError("transaction currency must be a three-letter uppercase ISO code")
            previous = self.session.scalar(
                select(TransactionCandidate)
                .where(
                    TransactionCandidate.source_message_id == source.id,
                    TransactionCandidate.source_item_index == source_item_index,
                )
                .order_by(TransactionCandidate.candidate_version.desc())
            )
            if previous is not None and previous.status in {CandidateStatus.APPROVED, CandidateStatus.IMPORTED}:
                raise WorkflowError("cannot reprocess an approved or imported candidate")
            if previous is not None:
                previous.status = CandidateStatus.DROPPED
                if previous.observation is not None:
                    previous.observation.status = ObservationStatus.SUPERSEDED
            candidate = TransactionCandidate(
                source_message_id=source.id,
                attempt_id=attempt.id,
                source_item_index=source_item_index,
                candidate_version=self._next_candidate_version(source.id, source_item_index),
                previous_candidate_id=previous.id if previous else None,
                status=CandidateStatus.UNDER_REVIEW,
                direction=transaction.direction,
                amount_minor=transaction.amount_minor,
                currency=transaction.currency,
                merchant=transaction.merchant,
                reference=transaction.reference,
                transaction_date=transaction.transaction_date,
                structured_payload={**(result.structured_output or {}), "source_item_index": source_item_index},
            )
            self.session.add(candidate)
            self.session.flush()
            observation = TransactionObservation(
                source_message_id=source.id,
                processing_attempt_id=attempt.id,
                candidate_id=candidate.id,
                account_id=self._find_or_create_account(
                    issuer=transaction.issuer,
                    external_reference=transaction.account_reference,
                ).id if transaction.issuer and transaction.account_reference else None,
                source_item_index=source_item_index,
                observation_version=candidate.candidate_version,
                status=ObservationStatus.PROVISIONAL,
                direction=transaction.direction,
                amount_minor=transaction.amount_minor,
                currency=transaction.currency,
                merchant=transaction.merchant,
                reference=transaction.reference,
                transaction_date=transaction.transaction_date,
            )
            self.session.add(observation)
            task = ReviewTask(candidate_id=candidate.id, state="open")
            self.session.add(task)
            self._audit(run, "candidate", candidate.id, AuditEventKind.CANDIDATE_PROPOSED)
            candidates.append(candidate)
            tasks.append(task)
        source.status = SourceMessageStatus.CONSUMED
        self._advance_cursor(source)
        self.session.flush()
        if candidates:
            self._emit_notification(
                run,
                kind="review_pending",
                title="Review Pending",
                body=f"{len(candidates)} transaction(s) need review",
                entity_kind="source_message",
                entity_id=source.id,
                metadata={"candidate_count": len(candidates)},
            )
        return source, tuple(candidates), tuple(tasks)

    def _record_statement(
        self,
        *,
        run: ExecutionRun,
        source: SourceMessage,
        attempt: ProcessingAttempt,
        result: ExtractionResult,
    ) -> BankStatement:
        """Persist a bank document and proposed reconciliation links.

        A statement never emits direct candidates: its lines are posted
        evidence reviewed together through ``StatementReviewBatch``.
        """

        statement_data = result.statement
        if statement_data is None:  # guarded by ExtractionResult, retained for runtime clarity
            raise WorkflowError("statement extraction requires statement metadata")
        account = self._find_or_create_account(
            issuer=statement_data.issuer,
            external_reference=statement_data.account_reference,
        )
        document_fingerprint = self._statement_document_fingerprint(
            account, statement_data, result.transactions
        )
        existing_document = self.session.scalar(
            select(BankStatement).where(
                BankStatement.account_id == account.id,
                BankStatement.document_fingerprint == document_fingerprint,
            )
        )
        if existing_document is not None:
            self._audit(
                run,
                "bank_statement",
                existing_document.id,
                AuditEventKind.STATEMENT_INGESTED,
                {
                    "duplicate_source_message_id": str(source.id),
                    "same_source": existing_document.source_message_id == source.id,
                },
            )
            return existing_document
        previous = self.session.scalar(
            select(BankStatement)
            .where(BankStatement.source_message_id == source.id)
            .order_by(BankStatement.statement_version.desc())
        )
        if previous is not None and previous.status == StatementStatus.APPROVED:
            raise WorkflowError("cannot reprocess an approved statement")
        if previous is not None:
            previous.status = StatementStatus.SUPERSEDED
            if previous.review_batch is not None and previous.review_batch.state == "open":
                previous.review_batch.state = "superseded"
        statement = BankStatement(
            source_message_id=source.id,
            processing_attempt_id=attempt.id,
            account_id=account.id,
            statement_version=(previous.statement_version + 1) if previous else 1,
            status=StatementStatus.OPEN,
            document_fingerprint=document_fingerprint,
            period_start=statement_data.period_start,
            period_end=statement_data.period_end,
            statement_date=statement_data.statement_date,
            currency=statement_data.currency,
            opening_balance_minor=statement_data.opening_balance_minor,
            closing_balance_minor=statement_data.closing_balance_minor,
        )
        self.session.add(statement)
        self.session.flush()
        self.session.add(StatementReviewBatch(statement_id=statement.id, state="open"))
        for line_index, transaction in enumerate(result.transactions, start=1):
            self._validate_transaction(transaction.amount_minor, transaction.currency)
            line = BankStatementLine(
                statement_id=statement.id,
                line_index=line_index,
                external_reference=transaction.reference,
                line_fingerprint=self._statement_line_fingerprint(account, transaction),
                direction=transaction.direction,
                amount_minor=transaction.amount_minor,
                currency=transaction.currency,
                merchant=transaction.merchant,
                description=transaction.reference,
                transaction_date=transaction.transaction_date,
                posting_date=transaction.posting_date,
                running_balance_minor=transaction.running_balance_minor,
                event_status=transaction.event_status,
                related_reference=transaction.related_reference,
            )
            self.session.add(line)
            self.session.flush()
            self._propose_reconciliation(line)
        self._audit(run, "bank_statement", statement.id, AuditEventKind.STATEMENT_INGESTED)
        return statement

    def _find_or_create_account(
        self, *, issuer: str | None, external_reference: str | None
    ) -> FinancialAccount:
        if not issuer or not external_reference:
            raise WorkflowError("bank account identity requires issuer and account reference")
        canonical_ref = canonical_external_reference(issuer, external_reference)
        account = self.session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.issuer == issuer,
                FinancialAccount.external_reference == canonical_ref,
            )
        )
        if account is None:
            account = FinancialAccount(
                issuer=issuer,
                external_reference=canonical_ref,
            )
            self.session.add(account)
            self.session.flush()
        return account

    def _propose_reconciliation(self, line: BankStatementLine) -> ReconciliationLink:
        """Use only conservative, account-scoped exact matches automatically."""

        observation_query = (
            select(TransactionObservation)
            .where(
                TransactionObservation.account_id == line.statement.account_id,
                TransactionObservation.status == ObservationStatus.PROVISIONAL,
                TransactionObservation.amount_minor == line.amount_minor,
                TransactionObservation.currency == line.currency,
                TransactionObservation.direction == line.direction,
            )
            .outerjoin(ReconciliationLink)
            .where(ReconciliationLink.id.is_(None))
        )
        observations = self.session.scalars(observation_query).all()
        reference = self._normalized_text(line.external_reference)
        reference_matches = [
            observation for observation in observations
            if reference and reference == self._normalized_text(observation.reference)
        ]
        if len(reference_matches) == 1:
            return self._add_reconciliation_link(
                line,
                outcome=ReconciliationOutcome.MATCHED,
                method=ReconciliationMethod.EXACT_REFERENCE,
                observation=reference_matches[0],
                confidence=1.0,
            )
        if len(reference_matches) > 1:
            return self._add_reconciliation_link(
                line,
                outcome=ReconciliationOutcome.AMBIGUOUS,
                method=ReconciliationMethod.EXACT_REFERENCE,
                confidence=None,
            )
        merchant = self._normalized_text(line.merchant)
        details_matches = [
            observation for observation in observations
            if line.transaction_date is not None
            and line.transaction_date == observation.transaction_date
            and merchant
            and merchant == self._normalized_text(observation.merchant)
        ]
        if len(details_matches) == 1:
            return self._add_reconciliation_link(
                line,
                outcome=ReconciliationOutcome.MATCHED,
                method=ReconciliationMethod.EXACT_DETAILS,
                observation=details_matches[0],
                confidence=0.95,
            )
        if len(details_matches) > 1:
            return self._add_reconciliation_link(
                line,
                outcome=ReconciliationOutcome.AMBIGUOUS,
                method=ReconciliationMethod.EXACT_DETAILS,
                confidence=None,
            )
        return self._add_reconciliation_link(
            line,
            outcome=ReconciliationOutcome.NEW,
            method=ReconciliationMethod.NONE,
            confidence=1.0,
        )

    def resolve_statement_line(
        self,
        *,
        run: ExecutionRun,
        line: BankStatementLine,
        outcome: ReconciliationOutcome,
        observation: TransactionObservation | None = None,
        note: str | None = None,
    ) -> ReconciliationLink:
        """Apply the human resolution needed for ambiguous statement evidence."""

        if line.statement.status != StatementStatus.OPEN:
            raise WorkflowError("only an open statement can be reconciled")
        if outcome == ReconciliationOutcome.MATCHED and observation is None:
            raise WorkflowError("a matched reconciliation requires an observation")
        if outcome != ReconciliationOutcome.MATCHED and observation is not None:
            raise WorkflowError("only a matched reconciliation may reference an observation")
        if observation is not None and observation.account_id != line.statement.account_id:
            raise WorkflowError("observation account does not match statement account")
        link = line.resolution
        if link is None:
            link = self._add_reconciliation_link(
                line,
                outcome=outcome,
                method=ReconciliationMethod.MANUAL,
                observation=observation,
                confidence=1.0,
                note=note,
            )
        else:
            link.outcome = outcome
            link.method = ReconciliationMethod.MANUAL
            link.observation = observation
            link.confidence = 1.0
            link.note = note
        self._audit(run, "reconciliation_link", link.id, AuditEventKind.RECONCILIATION_RESOLVED)
        self.session.flush()
        return link

    def map_financial_account(
        self,
        *,
        run: ExecutionRun,
        account: FinancialAccount,
        wallet_account_reference: str,
    ) -> FinancialAccount:
        """Persist the explicit bank-account to Wallet-account mapping."""

        mapped_reference = wallet_account_reference.strip()
        if not mapped_reference:
            raise WorkflowError("wallet account reference must not be blank")
        account.wallet_account_reference = mapped_reference
        self._audit(
            run,
            "financial_account",
            account.id,
            AuditEventKind.FINANCIAL_ACCOUNT_MAPPED,
            {"wallet_account_reference": mapped_reference},
        )
        self.session.flush()
        return account

    def approve_statement_batch(
        self,
        *,
        run: ExecutionRun,
        batch: StatementReviewBatch,
        reviewer_id: str,
        note: str | None = None,
    ) -> tuple[FinancialEvent, ...]:
        """Approve a reconciled statement as one bulk decision.

        Canonical events are created only here. Their Wallet import remains a
        separate, explicit command and cannot be issued for an unmapped account.
        """

        statement = batch.statement
        if batch.state != "open" or statement.status != StatementStatus.OPEN:
            raise WorkflowError("only an open statement review batch can be approved")
        lines = list(statement.lines)
        if not lines or any(line.resolution is None for line in lines):
            raise WorkflowError("every statement line requires a reconciliation resolution")
        if any(line.resolution and line.resolution.outcome == ReconciliationOutcome.AMBIGUOUS for line in lines):
            raise WorkflowError("ambiguous statement lines require manual resolution")
        events: list[FinancialEvent] = []
        for line in lines:
            resolution = line.resolution
            if resolution is None or resolution.outcome == ReconciliationOutcome.IGNORED:
                continue
            if resolution.outcome == ReconciliationOutcome.MATCHED and resolution.observation is not None:
                resolution.observation.status = ObservationStatus.CONFIRMED
                candidate = resolution.observation.candidate
                if candidate.status == CandidateStatus.UNDER_REVIEW:
                    candidate.status = CandidateStatus.DROPPED
                    if candidate.review_task is not None and candidate.review_task.state == "open":
                        candidate.review_task.state = "superseded"
            event = FinancialEvent(
                account_id=statement.account_id,
                statement_line_id=line.id,
                status=line.event_status,
                direction=line.direction,
                amount_minor=line.amount_minor,
                currency=line.currency,
                merchant=line.merchant,
                reference=line.external_reference,
                transaction_date=line.transaction_date,
                posting_date=line.posting_date,
                reverses_event_id=self._find_reversed_event_id(
                    account_id=statement.account_id,
                    event_status=line.event_status,
                    related_reference=line.related_reference,
                ),
            )
            self.session.add(event)
            events.append(event)
        batch.state = "approved"
        batch.reviewer_id = reviewer_id
        batch.decided_at = self.now()
        batch.decision_note = note
        statement.status = StatementStatus.APPROVED
        self.session.flush()
        self._audit(
            run,
            "statement_review_batch",
            batch.id,
            AuditEventKind.STATEMENT_BATCH_DECIDED,
            {"decision": "approved", "financial_event_count": len(events)},
        )
        self._emit_notification(
            run,
            kind="batch_approved",
            title="Statement Batch Approved",
            body=f"{len(events)} financial event(s) created",
            entity_kind="statement_review_batch",
            entity_id=batch.id,
            metadata={"financial_event_count": len(events)},
        )
        return tuple(events)

    def _add_reconciliation_link(
        self,
        line: BankStatementLine,
        *,
        outcome: ReconciliationOutcome,
        method: ReconciliationMethod,
        observation: TransactionObservation | None = None,
        confidence: float | None,
        note: str | None = None,
    ) -> ReconciliationLink:
        link = ReconciliationLink(
            statement_line_id=line.id,
            observation_id=observation.id if observation else None,
            outcome=outcome,
            method=method,
            confidence=confidence,
            note=note,
        )
        self.session.add(link)
        self.session.flush()
        return link

    @staticmethod
    def _normalized_text(value: str | None) -> str:
        return " ".join(value.casefold().split()) if value else ""

    def _statement_line_fingerprint(self, account: FinancialAccount, transaction: object) -> str:
        direction = getattr(transaction, "direction")
        amount_minor = getattr(transaction, "amount_minor")
        currency = getattr(transaction, "currency")
        transaction_date = getattr(transaction, "transaction_date")
        posting_date = getattr(transaction, "posting_date")
        reference = getattr(transaction, "reference")
        merchant = getattr(transaction, "merchant")
        event_status = getattr(transaction, "event_status")
        related_reference = getattr(transaction, "related_reference")
        return _digest(
            ":".join(
                str(value) for value in (
                    account.id, direction, amount_minor, currency, transaction_date,
                    posting_date, self._normalized_text(reference), self._normalized_text(merchant),
                    event_status, self._normalized_text(related_reference),
                )
            )
        )

    def _statement_document_fingerprint(
        self,
        account: FinancialAccount,
        statement: object,
        transactions: tuple[object, ...],
    ) -> str:
        document_fields = (
            account.id,
            getattr(statement, "period_start"),
            getattr(statement, "period_end"),
            getattr(statement, "statement_date"),
            getattr(statement, "currency"),
            getattr(statement, "opening_balance_minor"),
            getattr(statement, "closing_balance_minor"),
        )
        line_fingerprints = tuple(
            self._statement_line_fingerprint(account, transaction)
            for transaction in transactions
        )
        return _digest(":".join(str(value) for value in (*document_fields, *line_fingerprints)))

    def _find_reversed_event_id(
        self,
        *,
        account_id: object,
        event_status: FinancialEventStatus,
        related_reference: str | None,
    ) -> object | None:
        if event_status == FinancialEventStatus.POSTED or not related_reference:
            return None
        matches = self.session.scalars(
            select(FinancialEvent).where(
                FinancialEvent.account_id == account_id,
                FinancialEvent.reference == related_reference,
            )
        ).all()
        return matches[0].id if len(matches) == 1 else None

    @staticmethod
    def _validate_transaction(amount_minor: int, currency: str) -> None:
        if amount_minor <= 0:
            raise WorkflowError("transaction amount must be strictly positive")
        if len(currency) != 3 or not currency.isupper():
            raise WorkflowError("transaction currency must be a three-letter uppercase ISO code")

    def decide_review(
        self,
        *,
        run: ExecutionRun,
        task: ReviewTask,
        reviewer_id: str,
        decision: ReviewDecision,
        rejection_reason: str | None = None,
    ) -> ReviewDecisionRecord:
        candidate = task.candidate
        record = ReviewDecisionRecord(
            review_task_id=task.id,
            candidate_id=candidate.id,
            reviewer_id=reviewer_id,
            decision=decision,
            rejection_reason=rejection_reason,
            decided_at=self.now(),
        )
        self.session.add(record)
        task.state = "decided" if decision != ReviewDecision.DEFERRED else "superseded"
        candidate.status = (
            CandidateStatus.APPROVED
            if decision == ReviewDecision.APPROVED
            else CandidateStatus.REJECTED
        )
        if decision == ReviewDecision.REJECTED and candidate.observation is not None:
            candidate.observation.status = ObservationStatus.REJECTED
        self._audit(run, "review_task", task.id, AuditEventKind.REVIEW_DECISION)
        self.session.flush()
        return record

    def import_approved_candidate(
        self,
        *,
        run: ExecutionRun,
        candidate: TransactionCandidate,
        wallet: WalletClient | None,
    ) -> ImportCommand:
        """Reject legacy candidate imports.

        Candidates are notification observations, not authoritative financial
        events. Only an approved statement batch can create importable events.
        """

        del run, candidate, wallet
        raise WorkflowError(
            "notification candidates are provisional; import an approved statement event"
        )

    def import_approved_financial_event(
        self,
        *,
        run: ExecutionRun,
        event: FinancialEvent,
        wallet: WalletClient | None,
    ) -> ImportCommand:
        """Issue the explicit Wallet command for an approved statement event."""

        statement = event.statement_line.statement
        if statement.status != StatementStatus.APPROVED:
            raise WorkflowError("only an approved statement event may be imported")
        mapping_service = AccountMappingService(self.session)
        mapping = mapping_service.get_active_mapping(event.account_id)
        if mapping is None:
            raise WorkflowError("financial account must have an active validated mapping before import")
        command = self.session.scalar(
            select(ImportCommand).where(ImportCommand.financial_event_id == event.id)
        )
        if command is None:
            payload: dict[str, object] = {
                "amount": event.amount_minor,
                "currency": event.currency,
                "paymentType": str(event.direction),
                "counterParty": event.merchant or "",
                "note": event.reference or "",
                "accountReference": mapping.remote_account_id,
            }
            command = ImportCommand(
                execution_run_id=run.id,
                financial_event_id=event.id,
                idempotency_key=_digest(f"wallet-import:event:{event.id}"),
                status=ImportCommandStatus.QUEUED,
                payload=payload,
                issued_at=self.now(),
            )
            self.session.add(command)
            self.session.flush()
            self._audit(run, "import_command", command.id, AuditEventKind.IMPORT_COMMAND_ISSUED)

        if run.mode == IntegrationMode.DRY_RUN:
            self._audit(
                run,
                "import_command",
                command.id,
                AuditEventKind.IMPORT_COMMAND_TRANSITION,
                {"mode": "dry_run", "intent": "wallet_submit", "submitted": False},
            )
            self._emit_notification(
                run,
                kind="import_complete",
                title="Import Complete (dry-run)",
                body=f"Import command {command.id} status: {command.status.value} (dry-run)",
                entity_kind="import_command",
                entity_id=command.id,
            )
            return command
        if run.mode == IntegrationMode.DISABLED:
            raise WorkflowError("disabled runs cannot submit Wallet imports")
        if wallet is None:
            raise WorkflowError("live Wallet submission requires a Wallet client")

        command.status = ImportCommandStatus.IN_FLIGHT
        self.session.flush()
        result = wallet.submit(
            idempotency_key=command.idempotency_key,
            payload=command.payload,
        )
        attempt = WalletAttempt(
            execution_run_id=run.id,
            import_command_id=command.id,
            attempt_index=self._next_wallet_attempt_index(command.id),
            status=result.status,
            provider_request=result.request,
            provider_response=result.response,
            error_kind=result.error_kind,
            error_message=result.error_message,
            submitted_at=self.now(),
            acknowledged_at=self.now() if result.status == WalletAttemptStatus.ACKNOWLEDGED else None,
        )
        self.session.add(attempt)
        command.status = {
            WalletAttemptStatus.ACKNOWLEDGED: ImportCommandStatus.SUCCEEDED,
            WalletAttemptStatus.SUBMITTED: ImportCommandStatus.SUCCEEDED,
            WalletAttemptStatus.FAILED: ImportCommandStatus.FAILED,
            WalletAttemptStatus.UNKNOWN: ImportCommandStatus.UNKNOWN,
        }.get(result.status, ImportCommandStatus.FAILED)
        self._audit(
            run,
            "import_command",
            command.id,
            AuditEventKind.IMPORT_COMMAND_TRANSITION,
            {"mode": "live", "wallet_attempt_status": result.status.value},
        )

        self._emit_notification(
            run,
            kind="import_complete",
            title="Import Complete",
            body=f"Import command {command.id} status: {command.status.value}",
            entity_kind="import_command",
            entity_id=command.id,
        )
        return command

    def _record_source(self, run: ExecutionRun, message: MailboxMessage) -> SourceMessage:
        inbox = self.session.scalar(
            select(Inbox).where(
                Inbox.provider == message.provider,
                Inbox.account_fingerprint == message.account_fingerprint,
                Inbox.folder == message.folder,
            )
        )
        if inbox is None:
            inbox = Inbox(
                provider=message.provider,
                account_fingerprint=message.account_fingerprint,
                folder=message.folder,
                status=MailboxSourceStatus.ACTIVE,
            )
            self.session.add(inbox)
            self.session.flush()
        source = self.session.scalar(
            select(SourceMessage).where(
                SourceMessage.inbox_id == inbox.id,
                SourceMessage.uid_validity == message.uid_validity,
                SourceMessage.message_uid == message.message_uid,
            )
        )
        if source is not None:
            return source
        source = SourceMessage(
            execution_run_id=run.id,
            inbox_id=inbox.id,
            uid_validity=message.uid_validity,
            message_uid=message.message_uid,
            content_hash=_digest(message.body_text),
            status=SourceMessageStatus.RECEIVED,
            received_at=message.received_at,
        )
        self.session.add(source)
        self.session.flush()
        self.session.add(
            MessageContentMetadata(
                source_message_id=source.id,
                sender=message.sender,
                recipient=message.recipient,
                subject=message.subject,
                message_id_header=message.message_id_header,
            )
        )
        self._audit(run, "source_message", source.id, AuditEventKind.SOURCE_MESSAGE_RECEIVED)
        return source

    def _advance_cursor(self, source: SourceMessage) -> None:
        """Commit a mailbox cursor only once local processing has succeeded."""

        inbox = source.inbox
        should_advance = (
            inbox.uid_validity is None
            or inbox.uid_validity != source.uid_validity
            or (inbox.last_seen_uid is not None and source.message_uid > inbox.last_seen_uid)
        )
        if not should_advance:
            return
        inbox.uid_validity = source.uid_validity
        inbox.last_seen_uid = source.message_uid
        observed_at = self.now()
        inbox.last_observed_at = observed_at
        self.session.add(
            InboxCursorHistory(
                inbox_id=inbox.id,
                uid_validity=source.uid_validity,
                last_seen_uid=source.message_uid,
                observed_at=observed_at,
            )
        )

    def _record_attempt(self, run: ExecutionRun, source: SourceMessage, result: ExtractionResult) -> ProcessingAttempt:
        index = self.session.scalar(
            select(func.coalesce(func.max(ProcessingAttempt.attempt_index), 0)).where(
                ProcessingAttempt.source_message_id == source.id
            )
        ) + 1
        status = AttemptStatus.SUCCEEDED
        attempt = ProcessingAttempt(
            execution_run_id=run.id,
            source_message_id=source.id,
            attempt_index=index,
            idempotency_key=_digest(f"extract:{source.id}:{index}"),
            status=status,
            model_id=result.model_id,
            model_version=result.model_version,
            raw_response=result.raw_response,
            structured_output=result.structured_output,
            token_usage=result.token_usage,
        )
        self.session.add(attempt)
        self.session.flush()
        self._audit(run, "processing_attempt", attempt.id, AuditEventKind.ATTEMPT_CREATED)
        return attempt

    def _next_candidate_version(self, source_id: object, source_item_index: int) -> int:
        return self.session.scalar(
            select(func.coalesce(func.max(TransactionCandidate.candidate_version), 0)).where(
                TransactionCandidate.source_message_id == source_id,
                TransactionCandidate.source_item_index == source_item_index,
            )
        ) + 1

    def _next_wallet_attempt_index(self, command_id: object) -> int:
        return self.session.scalar(
            select(func.coalesce(func.max(WalletAttempt.attempt_index), 0)).where(
                WalletAttempt.import_command_id == command_id
            )
        ) + 1

    def _audit(
        self,
        run: ExecutionRun,
        entity_kind: str,
        entity_id: object,
        event_kind: AuditEventKind,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            AuditEvent(
                execution_run_id=run.id,
                entity_kind=entity_kind,
                entity_id=entity_id,
                event_kind=event_kind,
                payload=payload,
                occurred_at=self.now(),
            )
        )

    def _emit_notification(
        self,
        run: ExecutionRun,
        *,
        kind: str,
        title: str,
        body: str,
        entity_kind: str,
        entity_id: object,
        metadata: dict[str, object] | None = None,
    ) -> None:
        intent = NotificationIntent(
            idempotency_key=_digest(f"notification:{kind}:{entity_id}"),
            kind=kind,
            title=title,
            body=body,
            entity_kind=entity_kind,
            entity_id=str(entity_id),
            metadata=metadata or {},
        )
        record = self._outbox.enqueue(intent)
        if record is None:
            return
        self._audit(
            run,
            "notification_outbox",
            entity_id,
            AuditEventKind.NOTIFICATION_ENQUEUED,
            {"intent_kind": kind, "idempotency_key": intent.idempotency_key},
        )

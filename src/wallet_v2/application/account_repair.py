"""Safe, transactional duplicate FinancialAccount merge and operator repair.

For cases where masking-length variation created separate FinancialAccount
rows for what is actually one account, this module provides:

* ``canonicalise_and_merge`` — merge all accounts under an issuer whose
  external references share a canonical form into one survivor.
* ``AccountMappingService`` is called at the end to create a validated
  mapping, so the repair is fully provenance-tracked.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import Session

from wallet_v2.application.account_mapping import (
    AccountMappingService,
    MappingError,
)
from wallet_v2.domain.enums import AuditEventKind
from wallet_v2.domain.reference import canonical_external_reference
from wallet_v2.persistence.models.audit import AuditEvent
from wallet_v2.persistence.models.reconciliation import (
    AccountMapping,
    BankStatement,
    FinancialAccount,
    FinancialEvent,
    TransactionObservation,
)
from wallet_v2.persistence.models.wallet_catalog import (
    CatalogSyncCursor,
    CatalogSyncSnapshot,
)


class AccountRepairError(ValueError):
    """Raised when a merge-repair violates policy or validation."""


@dataclass
class AccountRepairResult:
    """Outcome of a merge-repair operation, safe for JSON output."""

    survivor_account_id: str
    merged_account_ids: list[str] = field(default_factory=list)
    reassigned: dict[str, int] = field(default_factory=dict)
    mapping_account_id: str | None = None
    mapping_remote_id: str | None = None
    warnings: list[str] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_REASSIGNABLE_RELATIONS: list[tuple[str, type, str]] = [
    ("bank_statements", BankStatement, "account_id"),
    ("financial_events", FinancialEvent, "account_id"),
    ("transaction_observations", TransactionObservation, "account_id"),
]


class AccountRepairService:
    """Transactional, idempotent duplicate FinancialAccount merge.

    Typical usage (operators)::

        svc = AccountRepairService(session)
        result = svc.repair_qik_account(
            raw_references=["*2197", "************2197"],
            wallet_account_id="37c86c4f-5370-466b-a36b-40b533f6cf31",
        )
    """

    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self._session = session
        self._clock = clock or _utcnow

    def repair_qik_account(
        self,
        *,
        raw_references: list[str],
        wallet_account_id: str,
        issuer: str,
    ) -> AccountRepairResult:
        """Merge duplicate Qik FinancialAccounts and map the survivor.

        Idempotent: if the accounts are already merged or the mapping already
        exists this is a no-op.  Returns a summary with counts of reassigned
        dependent records.
        """
        result = self.canonicalise_and_merge(
            issuer=issuer, raw_references=raw_references
        )
        if result.mapping_account_id is None:
            mapping_svc = AccountMappingService(self._session, clock=self._clock)
            snapshot = self._current_accounts_snapshot()
            if snapshot is None:
                raise AccountRepairError(
                    "No current accounts catalog snapshot found; run wallet-v2 sync-catalog first"
                )
            mapping = mapping_svc.create_mapping(
                financial_account_id=uuid.UUID(result.survivor_account_id),
                remote_account_id=wallet_account_id,
                snapshot_id=snapshot.id,
            )
            self._session.flush()
            result.mapping_account_id = str(mapping.financial_account_id)
            result.mapping_remote_id = mapping.remote_account_id
        return result

    def canonicalise_and_merge(
        self,
        *,
        issuer: str,
        raw_references: list[str],
    ) -> AccountRepairResult:
        """Merge all FinancialAccounts for *issuer* whose external references
        normalise to the same canonical form.

        The method:
        1. Computes the canonical reference from the first raw reference.
        2. Finds or creates the canonical (survivor) account.
        3. Finds any duplicate accounts whose raw references normalise to the
           same canonical form.
        4. Checks for unsafe conflicts.
        5. Reassigns all dependent records to the survivor.
        6. Deletes the duplicate accounts.

        Idempotent: calling twice with the same arguments is safe.
        """
        if not raw_references:
            raise AccountRepairError("at least one external reference is required")

        canonical_references = {
            canonical_external_reference(issuer, reference)
            for reference in raw_references
        }
        if len(canonical_references) != 1 or not next(iter(canonical_references)):
            raise AccountRepairError(
                "all external references must resolve to one non-blank canonical reference"
            )
        canonical_ref = next(iter(canonical_references))

        survivor = self._session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.issuer == issuer,
                FinancialAccount.external_reference == canonical_ref,
            )
        )
        if survivor is None:
            survivor = FinancialAccount(
                issuer=issuer, external_reference=canonical_ref
            )
            self._session.add(survivor)
            self._session.flush()

        warnings: list[str] = []
        issuer_accounts = self._session.scalars(
            select(FinancialAccount).where(FinancialAccount.issuer == issuer)
        ).all()
        duplicates = [
            account
            for account in issuer_accounts
            if account.id != survivor.id
            and canonical_external_reference(issuer, account.external_reference)
            == canonical_ref
        ]

        if not duplicates:
            result = AccountRepairResult(
                survivor_account_id=str(survivor.id),
                mapping_account_id=(
                    str(survivor.id)
                    if self._has_active_mapping(survivor.id)
                    else None
                ),
                mapping_remote_id=(
                    self._active_mapping_remote_id(survivor.id)
                    if self._has_active_mapping(survivor.id)
                    else None
                ),
            )
            if self._has_active_mapping(survivor.id):
                result.warnings.append("Survivor already has an active mapping; no new mapping created")
            return result

        self._check_conflicts(survivor, duplicates, warnings)

        counts: dict[str, int] = {}
        for dup in duplicates:
            reassigned = self._reassign_dependents(from_id=dup.id, to_id=survivor.id)
            for key, val in reassigned.items():
                counts[key] = counts.get(key, 0) + val
            self._session.delete(dup)

        self._audit_merge(survivor.id, [d.id for d in duplicates], counts)

        self._session.flush()

        return AccountRepairResult(
            survivor_account_id=str(survivor.id),
            merged_account_ids=[str(d.id) for d in duplicates],
            reassigned=counts,
            warnings=warnings,
        )

    def _check_conflicts(
        self,
        survivor: FinancialAccount,
        duplicates: list[FinancialAccount],
        warnings: list[str],
    ) -> None:
        """Refuse a merge that would discard identity or document provenance."""
        for dup in duplicates:
            mapping = self._session.scalar(
                select(AccountMapping.id).where(
                    AccountMapping.financial_account_id == dup.id
                )
            )
            if mapping is not None:
                raise AccountRepairError(
                    f"duplicate {dup.id} has mapping history and cannot be deleted automatically"
                )
            if dup.wallet_account_reference != survivor.wallet_account_reference:
                raise AccountRepairError(
                    f"duplicate {dup.id} has a conflicting legacy Wallet account reference"
                )
            collisions = self._session.scalar(
                select(BankStatement.id).where(
                    BankStatement.account_id == survivor.id,
                    BankStatement.document_fingerprint.in_(
                        select(BankStatement.document_fingerprint).where(
                            BankStatement.account_id == dup.id
                        )
                    ),
                )
            )
            if collisions is not None:
                raise AccountRepairError(
                    f"duplicate {dup.id} has a statement document already present on the survivor"
                )

    def _reassign_dependents(
        self, *, from_id: uuid.UUID, to_id: uuid.UUID
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table_name, model, fk_column in _REASSIGNABLE_RELATIONS:
            stmt = (
                sa_update(model)
                .where(getattr(model, fk_column) == from_id)
                .values({fk_column: to_id})
            )
            result = self._session.execute(stmt)
            if result.rowcount:
                counts[table_name] = result.rowcount
        self._session.expire_all()
        return counts

    def _has_active_mapping(self, account_id: uuid.UUID) -> bool:
        mapping_svc = AccountMappingService(self._session, clock=self._clock)
        return mapping_svc.get_active_mapping(financial_account_id=account_id) is not None

    def _active_mapping_remote_id(self, account_id: uuid.UUID) -> str | None:
        mapping_svc = AccountMappingService(self._session, clock=self._clock)
        try:
            return mapping_svc.get_active_remote_account_id(financial_account_id=account_id)
        except MappingError:
            return None

    def _current_accounts_snapshot(self) -> CatalogSyncSnapshot | None:
        cursor = self._session.scalar(
            select(CatalogSyncCursor).where(
                CatalogSyncCursor.resource_kind == "accounts"
            )
        )
        if cursor is None or cursor.current_snapshot_id is None:
            return None
        return self._session.get(CatalogSyncSnapshot, cursor.current_snapshot_id)

    def _audit_merge(
        self,
        survivor_id: uuid.UUID,
        merged_ids: list[uuid.UUID],
        counts: dict[str, int],
    ) -> None:
        payload: dict[str, Any] = {
            "survivor_account_id": str(survivor_id),
            "merged_account_ids": [str(mid) for mid in merged_ids],
            "reassigned_counts": counts,
        }
        self._session.add(
            AuditEvent(
                entity_kind="financial_account",
                entity_id=survivor_id,
                event_kind=AuditEventKind.FINANCIAL_ACCOUNT_MERGED,
                payload=payload,
                occurred_at=self._clock(),
            )
        )

"""Validated FinancialAccount-to-Wallet-account mapping service.

Each mapping requires a current accounts catalog snapshot that contains the
target remote account ID and proves the account is not archived. Mappings are
append-only: superseding an active mapping creates a new snapshot-anchored
record and marks the previous one as superseded.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from wallet_v2.application.contracts import WalletCatalogRef
from wallet_v2.persistence.models.reconciliation import AccountMapping
from wallet_v2.persistence.models.wallet_catalog import (
    CatalogSyncCursor,
    CatalogSyncSnapshot,
)


class MappingError(ValueError):
    """Raised when a requested mapping violates policy or validation."""


def _check_not_archived(
    candidate: dict[str, Any], account_id: str
) -> None:
    archived = candidate.get("archived", False)
    if archived:
        raise MappingError(
            f"Remote account {account_id!r} is archived and cannot be mapped"
        )


class AccountMappingService:
    """Create, query, and supersede validated account mappings."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def create_mapping(
        self,
        *,
        financial_account_id: object,
        remote_account_id: str,
        snapshot_id: object,
    ) -> AccountMapping:
        """Validate and create a new active mapping.

        Requires:
        - The financial account exists (assumed by caller to have been loaded).
        - No active mapping already exists for the same financial account.
        - The snapshot exists, is for ``resource_kind == 'accounts'``.
        - The remote account ID appears among the snapshot items and is not
          archived.

        Returns the newly created ``AccountMapping`` row (flushed).
        """
        remote_account_id = remote_account_id.strip()
        if not remote_account_id:
            raise MappingError("remote_account_id must not be blank")

        existing = self.get_active_mapping(financial_account_id)
        if existing is not None:
            raise MappingError(
                "Financial account already has an active mapping; "
                "supersede it before creating a new one"
            )

        snapshot = self._session.get(CatalogSyncSnapshot, snapshot_id)
        if snapshot is None:
            raise MappingError(
                f"CatalogSyncSnapshot {snapshot_id!r} not found"
            )
        if snapshot.resource_kind != "accounts":
            raise MappingError(
                f"Snapshot {snapshot_id!r} has resource_kind "
                f"{snapshot.resource_kind!r}, expected 'accounts'"
            )
        cursor = self._session.scalar(
            select(CatalogSyncCursor).where(
                CatalogSyncCursor.resource_kind == "accounts"
            )
        )
        if cursor is None or cursor.current_snapshot_id != snapshot.id:
            raise MappingError(
                "Mapping must be validated against the current accounts snapshot"
            )

        items: list[dict[str, Any]] = snapshot.catalog_data.get("items", [])
        if not items:
            raise MappingError(
                f"Snapshot {snapshot_id!r} contains no accounts"
            )

        found = False
        for item in items:
            item_id = self._resolve_account_id(item)
            if item_id == remote_account_id:
                _check_not_archived(item, remote_account_id)
                found = True
                break
        if not found:
            raise MappingError(
                f"Remote account {remote_account_id!r} not found in "
                f"snapshot {snapshot_id!r}"
            )

        now = self._clock()
        mapping = AccountMapping(
            financial_account_id=financial_account_id,
            remote_account_id=remote_account_id,
            validated_snapshot_id=snapshot.id,
            validated_snapshot_version=snapshot.snapshot_version,
            validated_at=now,
        )
        self._session.add(mapping)
        self._session.flush()
        return mapping

    def supersede_mapping(
        self, financial_account_id: object
    ) -> AccountMapping | None:
        """Supersede the current active mapping, if one exists.

        Returns the superseded mapping, or ``None`` if no active mapping
        was found.
        """
        mapping = self._get_unsuperseded_mapping(financial_account_id)
        if mapping is None:
            return None
        mapping.superseded_at = self._clock()
        self._session.flush()
        return mapping

    def get_active_mapping(
        self, financial_account_id: object
    ) -> AccountMapping | None:
        mapping = self._get_unsuperseded_mapping(financial_account_id)
        if mapping is None:
            return None
        cursor = self._session.scalar(
            select(CatalogSyncCursor).where(
                CatalogSyncCursor.resource_kind == "accounts"
            )
        )
        return (
            mapping
            if cursor is not None and cursor.current_snapshot_id == mapping.validated_snapshot_id
            else None
        )

    def _get_unsuperseded_mapping(
        self, financial_account_id: object
    ) -> AccountMapping | None:
        return self._session.scalar(
            select(AccountMapping).where(
                AccountMapping.financial_account_id == financial_account_id,
                AccountMapping.superseded_at.is_(None),
            )
        )

    def get_active_remote_account_id(
        self, financial_account_id: object
    ) -> str:
        mapping = self.get_active_mapping(financial_account_id)
        if mapping is None:
            raise MappingError(
                "Financial account has no active validated mapping"
            )
        return mapping.remote_account_id

    @staticmethod
    def _resolve_account_id(item: dict[str, Any]) -> str:
        id_val = item.get("id")
        if isinstance(id_val, WalletCatalogRef):
            return id_val.id
        if isinstance(id_val, str):
            return id_val
        raise MappingError(f"Cannot resolve account identifier from {item!r}")

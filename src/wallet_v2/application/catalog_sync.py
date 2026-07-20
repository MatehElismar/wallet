"""Catalog sync service — atomic, versioned snapshot writes.

Implements Section 1 of the wallet-catalog-write-path-plan: synchronise
Wallet catalog resources (accounts, categories, labels, and record rules)
into versioned, immutable snapshots with per-resource sync
cursors.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wallet_v2.application.contracts import (
    WalletAccount,
    WalletCategory,
    WalletLabel,
    WalletRecordRule,
)
from wallet_v2.persistence.models.wallet_catalog import (
    CatalogSyncCursor,
    CatalogSyncSnapshot,
)

_RESOURCE_KINDS: tuple[str, ...] = (
    "accounts",
    "categories",
    "labels",
    "record_rules",
)


class CatalogReader(Protocol):
    """Protocol for reading catalog resources from Wallet REST.

    Each method returns a typed sequence of the corresponding resource.
    Implemented by ``BudgetBakersWalletClient``. Tests provide a stub.
    """

    def get_accounts(self) -> Sequence[WalletAccount]: ...
    def get_categories(self) -> Sequence[WalletCategory]: ...
    def get_labels(self) -> Sequence[WalletLabel]: ...
    def get_record_rules(self) -> Sequence[WalletRecordRule]: ...


def _serialise_items(items: Sequence[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]


def _next_snapshot_version(session: Session, resource_kind: str) -> int:
    """Return the next monotonic snapshot version for *resource_kind*."""
    max_version = session.scalar(
        select(func.coalesce(func.max(CatalogSyncSnapshot.snapshot_version), 0)).where(
            CatalogSyncSnapshot.resource_kind == resource_kind
        )
    )
    return (max_version or 0) + 1


def _get_or_create_cursor(
    session: Session, resource_kind: str
) -> CatalogSyncCursor:
    cursor = session.scalar(
        select(CatalogSyncCursor).where(
            CatalogSyncCursor.resource_kind == resource_kind
        )
    )
    if cursor is None:
        cursor = CatalogSyncCursor(resource_kind=resource_kind)
        session.add(cursor)
    return cursor


class CatalogSyncService:
    """Synchronise catalog resources into versioned snapshots.

    Each sync operation is atomic: a new snapshot row is created, the
    cursor is updated, and both are committed within the same
    transaction. No partial snapshot can become current.

    All read operations delegate to a ``CatalogReader`` so tests can
    inject stubs without network access.
    """

    def __init__(
        self,
        session: Session,
        reader: CatalogReader,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._reader = reader
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def sync_resource(
        self,
        resource_kind: str,
        *,
        remote_revision: str | None = None,
    ) -> CatalogSyncSnapshot:
        """Atomically sync one catalog resource kind.

        Returns the newly created ``CatalogSyncSnapshot``.
        """
        if resource_kind not in _RESOURCE_KINDS:
            raise ValueError(
                f"Unknown resource_kind {resource_kind!r}; "
                f"must be one of {_RESOURCE_KINDS}"
            )

        items = self._fetch_items(resource_kind)
        version = _next_snapshot_version(self._session, resource_kind)
        now = self._clock()

        snapshot = CatalogSyncSnapshot(
            resource_kind=resource_kind,
            snapshot_version=version,
            catalog_data={
                "version": 1,
                "resource_kind": resource_kind,
                "snapshot_version": version,
                "synced_at": now.isoformat(),
                "item_count": len(items),
                "items": _serialise_items(items),
            },
            remote_revision=remote_revision,
        )
        self._session.add(snapshot)

        cursor = _get_or_create_cursor(self._session, resource_kind)
        cursor.last_synced_at = now
        cursor.last_remote_revision = remote_revision
        cursor.current_snapshot = snapshot

        return snapshot

    def sync_all(
        self,
        *,
        remote_revision: str | None = None,
    ) -> dict[str, CatalogSyncSnapshot]:
        """Atomically sync every known catalog resource kind.

        Returns a mapping of resource_kind -> snapshot.
        """
        snapshots: dict[str, CatalogSyncSnapshot] = {}
        for kind in _RESOURCE_KINDS:
            snapshots[kind] = self.sync_resource(
                kind, remote_revision=remote_revision
            )
        return snapshots

    def _fetch_items(self, resource_kind: str) -> Sequence[Any]:
        fetch: Callable[[], Sequence[Any]]
        if resource_kind == "accounts":
            fetch = self._reader.get_accounts
        elif resource_kind == "categories":
            fetch = self._reader.get_categories
        elif resource_kind == "labels":
            fetch = self._reader.get_labels
        elif resource_kind == "record_rules":
            fetch = self._reader.get_record_rules
        else:
            raise ValueError(f"Unknown resource_kind: {resource_kind!r}")
        return fetch()

    @staticmethod
    def get_latest_snapshot(
        session: Session, resource_kind: str
    ) -> CatalogSyncSnapshot | None:
        return session.scalar(
            select(CatalogSyncSnapshot)
            .where(CatalogSyncSnapshot.resource_kind == resource_kind)
            .order_by(CatalogSyncSnapshot.snapshot_version.desc())
            .limit(1)
        )

    @staticmethod
    def get_cursor(
        session: Session, resource_kind: str
    ) -> CatalogSyncCursor | None:
        return session.scalar(
            select(CatalogSyncCursor).where(
                CatalogSyncCursor.resource_kind == resource_kind
            )
        )

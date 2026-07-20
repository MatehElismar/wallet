"""Catalog sync service tests — hermetic, no network access.

Tests the CatalogSyncSnapshot and CatalogSyncCursor ORM models, plus
the CatalogSyncService orchestration. All sync reads are driven by
in-memory stubs; no live Wallet API calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

import pytest
from sqlalchemy.orm import Session

from wallet_v2.application.catalog_sync import CatalogSyncService
from wallet_v2.application.contracts import (
    WalletAccount,
    WalletBalance,
    WalletCategory,
    WalletLabel,
    WalletRecordRule,
)
from wallet_v2.persistence.models.wallet_catalog import (
    CatalogSyncCursor,
    CatalogSyncSnapshot,
)


# ── stub catalog reader ───────────────────────────────────────────────


class _StubCatalogReader:
    def __init__(self) -> None:
        self.accounts: Sequence[WalletAccount] = (
            WalletAccount(
                id="a1",
                name="Cash",
                balance=WalletBalance(currency_code="USD", value=1000.0),
            ),
            WalletAccount(
                id="a2",
                name="Savings",
                balance=WalletBalance(currency_code="EUR", value=5000.0),
            ),
        )
        self.categories: Sequence[WalletCategory] = (
            WalletCategory(id="c1", name="Food", color="#4CAF50"),
            WalletCategory(id="c2", name="Transport", color="#2196F3", archived=True),
        )
        self.labels: Sequence[WalletLabel] = (
            WalletLabel(id="l1", name="Business", color="#333", archived=False),
        )
        self.rules: Sequence[WalletRecordRule] = ()

    def get_accounts(self) -> Sequence[WalletAccount]:
        return self.accounts

    def get_categories(self) -> Sequence[WalletCategory]:
        return self.categories

    def get_labels(self) -> Sequence[WalletLabel]:
        return self.labels

    def get_record_rules(self) -> Sequence[WalletRecordRule]:
        return self.rules


@pytest.fixture()
def stub_reader() -> _StubCatalogReader:
    return _StubCatalogReader()


@pytest.fixture()
def sync_service(session: Session, stub_reader: _StubCatalogReader) -> CatalogSyncService:
    return CatalogSyncService(session=session, reader=stub_reader)


# ── snapshot model constraints ────────────────────────────────────────


class TestCatalogSyncSnapshotModel:
    def test_snapshot_is_immutable(self, metadata_tables: dict[str, object]) -> None:
        table = metadata_tables.get("catalog_sync_snapshots")
        assert table is not None, "catalog_sync_snapshots table should be registered"
        columns = {col.name for col in table.columns}  # type: ignore[union-attr]
        assert "updated_at" not in columns, (
            "CatalogSyncSnapshot must not have updated_at (immutable)"
        )
        assert "created_at" in columns

    def test_can_create_snapshot(self, session: Session) -> None:
        snap = CatalogSyncSnapshot(
            resource_kind="accounts",
            snapshot_version=1,
            catalog_data={"items": [{"id": "a1"}]},
        )
        session.add(snap)
        session.commit()
        assert snap.id is not None
        assert snap.created_at is not None
        assert snap.snapshot_version == 1

    def test_snapshot_version_must_be_positive(self, session: Session) -> None:
        from sqlalchemy.exc import IntegrityError

        snap = CatalogSyncSnapshot(
            resource_kind="accounts",
            snapshot_version=0,
            catalog_data={"items": []},
        )
        session.add(snap)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_resource_kind_must_be_valid(self, session: Session) -> None:
        from sqlalchemy.exc import IntegrityError

        snap = CatalogSyncSnapshot(
            resource_kind="invalid_kind",
            snapshot_version=1,
            catalog_data={"items": []},
        )
        session.add(snap)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_kind_version_unique_constraint(self, session: Session) -> None:
        from sqlalchemy.exc import IntegrityError

        a = CatalogSyncSnapshot(
            resource_kind="accounts",
            snapshot_version=1,
            catalog_data={"items": [{"id": "a1"}]},
        )
        b = CatalogSyncSnapshot(
            resource_kind="accounts",
            snapshot_version=1,
            catalog_data={"items": [{"id": "a2"}]},
        )
        session.add_all([a, b])
        with pytest.raises(IntegrityError):
            session.commit()

    def test_different_kinds_same_version_ok(self, session: Session) -> None:
        a = CatalogSyncSnapshot(
            resource_kind="accounts",
            snapshot_version=1,
            catalog_data={"items": [{"id": "a1"}]},
        )
        b = CatalogSyncSnapshot(
            resource_kind="categories",
            snapshot_version=1,
            catalog_data={"items": [{"id": "c1"}]},
        )
        session.add_all([a, b])
        session.commit()
        assert a.created_at is not None
        assert b.created_at is not None


# ── cursor model constraints ──────────────────────────────────────────


class TestCatalogSyncCursorModel:
    def test_cursor_has_timestamped_mixin(self, metadata_tables: dict[str, object]) -> None:
        table = metadata_tables.get("catalog_sync_cursors")
        assert table is not None, "catalog_sync_cursors table should be registered"
        columns = {col.name for col in table.columns}  # type: ignore[union-attr]
        assert "updated_at" in columns, "CatalogSyncCursor must have updated_at"
        assert "created_at" in columns

    def test_can_create_cursor(self, session: Session) -> None:
        cursor = CatalogSyncCursor(resource_kind="accounts")
        session.add(cursor)
        session.commit()
        assert cursor.id is not None
        assert cursor.resource_kind == "accounts"
        assert cursor.last_synced_at is None

    def test_resource_kind_must_be_valid(self, session: Session) -> None:
        from sqlalchemy.exc import IntegrityError

        cursor = CatalogSyncCursor(resource_kind="bad_kind")
        session.add(cursor)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_resource_kind_unique(self, session: Session) -> None:
        from sqlalchemy.exc import IntegrityError

        a = CatalogSyncCursor(resource_kind="accounts")
        b = CatalogSyncCursor(resource_kind="accounts")
        session.add_all([a, b])
        with pytest.raises(IntegrityError):
            session.commit()

    def test_cursor_links_to_snapshot(self, session: Session) -> None:
        snap = CatalogSyncSnapshot(
            resource_kind="accounts",
            snapshot_version=1,
            catalog_data={"items": [{"id": "a1"}]},
        )
        cursor = CatalogSyncCursor(
            resource_kind="accounts",
            last_synced_at=datetime(2025, 7, 20, tzinfo=timezone.utc),
            current_snapshot=snap,
        )
        session.add_all([snap, cursor])
        session.commit()
        assert cursor.current_snapshot_id == snap.id
        assert cursor.current_snapshot is snap


# ── sync service ──────────────────────────────────────────────────────


class TestCatalogSyncService:
    def test_sync_accounts_creates_snapshot_and_updates_cursor(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        snapshot = sync_service.sync_resource("accounts")
        session.commit()

        assert snapshot.resource_kind == "accounts"
        assert snapshot.snapshot_version == 1
        assert snapshot.catalog_data["item_count"] == 2
        assert snapshot.catalog_data["resource_kind"] == "accounts"
        items = snapshot.catalog_data["items"]
        assert len(items) == 2
        assert items[0]["id"] == "a1"

        cursor = CatalogSyncService.get_cursor(session, "accounts")
        assert cursor is not None
        assert cursor.last_synced_at is not None
        assert cursor.current_snapshot_id == snapshot.id

    def test_sync_categories_creates_snapshot(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        snapshot = sync_service.sync_resource("categories")
        session.commit()

        assert snapshot.resource_kind == "categories"
        assert snapshot.snapshot_version == 1
        assert snapshot.catalog_data["item_count"] == 2
        items = snapshot.catalog_data["items"]
        names = {item["name"] for item in items}
        assert "Food" in names
        assert "Transport" in names

    def test_sync_labels_creates_snapshot(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        snapshot = sync_service.sync_resource("labels")
        session.commit()

        assert snapshot.resource_kind == "labels"
        assert snapshot.snapshot_version == 1
        assert snapshot.catalog_data["item_count"] == 1

    def test_sync_record_rules_handles_empty(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        snapshot = sync_service.sync_resource("record_rules")
        session.commit()

        assert snapshot.resource_kind == "record_rules"
        assert snapshot.snapshot_version == 1
        assert snapshot.catalog_data["item_count"] == 0

    def test_second_sync_increments_version(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        snap1 = sync_service.sync_resource("accounts")
        session.commit()
        assert snap1.snapshot_version == 1

        snap2 = sync_service.sync_resource("accounts")
        session.commit()
        assert snap2.snapshot_version == 2

        cursor = CatalogSyncService.get_cursor(session, "accounts")
        assert cursor is not None
        assert cursor.current_snapshot_id == snap2.id

    def test_sync_stores_remote_revision(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        snapshot = sync_service.sync_resource(
            "accounts",
            remote_revision='"abc123"',
        )
        session.commit()

        assert snapshot.remote_revision == '"abc123"'
        cursor = CatalogSyncService.get_cursor(session, "accounts")
        assert cursor is not None
        assert cursor.last_remote_revision == '"abc123"'

    def test_sync_all_creates_snapshot_for_every_kind(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        snapshots = sync_service.sync_all(remote_revision='"v1"')
        session.commit()

        expected_kinds = {"accounts", "categories", "labels", "record_rules"}
        assert set(snapshots.keys()) == expected_kinds
        for kind, snap in snapshots.items():
            assert snap.resource_kind == kind
            assert snap.snapshot_version == 1

    def test_invalid_resource_kind_raises(
        self, sync_service: CatalogSyncService
    ) -> None:
        with pytest.raises(ValueError, match="Unknown resource_kind"):
            sync_service.sync_resource("unknown_kind")

    def test_get_latest_snapshot_returns_most_recent(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        sync_service.sync_resource("accounts")
        session.commit()
        sync_service.sync_resource("accounts")
        session.commit()

        latest = CatalogSyncService.get_latest_snapshot(session, "accounts")
        assert latest is not None
        assert latest.snapshot_version == 2

    def test_get_latest_snapshot_returns_none_for_unknown_kind(
        self, session: Session,
    ) -> None:
        result = CatalogSyncService.get_latest_snapshot(session, "accounts")
        assert result is None

    def test_get_cursor_returns_none_for_unknown_kind(
        self, session: Session,
    ) -> None:
        result = CatalogSyncService.get_cursor(session, "accounts")
        assert result is None

    def test_cursor_is_reused_across_syncs(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        sync_service.sync_resource("accounts")
        session.commit()
        cursor1 = CatalogSyncService.get_cursor(session, "accounts")
        assert cursor1 is not None

        sync_service.sync_resource("accounts")
        session.commit()
        cursor2 = CatalogSyncService.get_cursor(session, "accounts")
        assert cursor2 is not None

        assert cursor1.id == cursor2.id

    def test_sync_preserves_version_per_kind(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        sync_service.sync_resource("accounts")
        session.commit()
        sync_service.sync_resource("accounts")
        session.commit()
        sync_service.sync_resource("categories")
        session.commit()

        assert (
            CatalogSyncService.get_latest_snapshot(session, "accounts").snapshot_version  # type: ignore[union-attr]
            == 2
        )
        assert (
            CatalogSyncService.get_latest_snapshot(session, "categories").snapshot_version  # type: ignore[union-attr]
            == 1
        )

    def test_snapshot_data_is_hermetic_json_serializable(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        import json

        snapshot = sync_service.sync_resource("accounts")
        session.commit()

        raw = snapshot.catalog_data
        roundtripped = json.loads(json.dumps(raw))
        assert roundtripped == raw

    def test_sync_is_atomic(
        self, sync_service: CatalogSyncService, session: Session
    ) -> None:
        snapshot = sync_service.sync_resource("accounts")
        cursor = CatalogSyncService.get_cursor(session, "accounts")

        assert snapshot.id is not None
        assert cursor is not None
        assert cursor.current_snapshot_id is not None

        session.commit()
        session.refresh(snapshot)
        session.refresh(cursor)

        assert cursor.current_snapshot_id == snapshot.id

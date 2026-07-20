"""Wallet catalog-sync snapshots and cursors.

Two tables implement the versioned catalog synchronization contract
from Section 1 of the wallet-catalog-write-path-plan:

* :class:`CatalogSyncSnapshot` — an immutable, versioned full snapshot
  of one catalog resource kind. The snapshot data plus its version are
  written atomically; no partial snapshot can become current.
* :class:`CatalogSyncCursor` — per-resource sync state tracking the
  last successful sync timestamp, remote revision, and a pointer to the
  current snapshot. Used to enable efficient incremental syncs once the
  Wallet API exposes change metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.persistence.base import Base, Immutable, Timestamped
from wallet_v2.persistence.types import JSONB

if TYPE_CHECKING:
    pass


class CatalogSyncSnapshot(Base, Immutable):
    """Immutable, versioned snapshot of one catalog resource kind.

    Each row is append-only (never updated). The ``snapshot_version`` is
    monotonically increasing per ``resource_kind`` so consumers can
    determine whether a newer snapshot exists without comparing full
    data blobs.

    The ``remote_revision`` captures any server-supplied revision
    metadata (e.g. an ETag or ``lastModified`` timestamp) for efficient
    future syncs. When the upstream does not expose revisions, the
    field is null.
    """

    __tablename__ = "catalog_sync_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "resource_kind",
            "snapshot_version",
            name="uq_catalog_snapshots_kind_version",
        ),
        CheckConstraint(
            "snapshot_version >= 1",
            name="ck_catalog_snapshots_version_positive",
        ),
        CheckConstraint(
            "resource_kind IN ('accounts', 'categories', 'labels', "
            "'record_rules')",
            name="ck_catalog_snapshots_resource_kind",
        ),
        Index(
            "ix_catalog_snapshots_kind_version",
            "resource_kind",
            "snapshot_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    catalog_data: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)
    remote_revision: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )


class CatalogSyncCursor(Base, Timestamped):
    """Per-resource sync state for efficient incremental catalog sync.

    One cursor exists for each distinct ``resource_kind``. After every
    successful sync the cursor is updated to point at the newest
    snapshot and record the upstream revision (if available).
    """

    __tablename__ = "catalog_sync_cursors"
    __table_args__ = (
        UniqueConstraint(
            "resource_kind",
            name="uq_catalog_sync_cursors_kind",
        ),
        CheckConstraint(
            "resource_kind IN ('accounts', 'categories', 'labels', "
            "'record_rules')",
            name="ck_catalog_sync_cursors_resource_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_remote_revision: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_sync_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_snapshot: Mapped[CatalogSyncSnapshot | None] = relationship(
        foreign_keys=[current_snapshot_id],
    )

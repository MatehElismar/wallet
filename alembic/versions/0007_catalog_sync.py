"""Create Wallet catalog sync snapshot and cursor tables.

Revision ID: 0007_catalog_sync
Revises: 0006_push_notifications
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_catalog_sync"
down_revision = "0006_push_notifications"
branch_labels = None
depends_on = None


def _uuid() -> "sa.TypeEngine[object]":
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "catalog_sync_snapshots",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "resource_kind",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "snapshot_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "catalog_data",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "remote_revision",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_catalog_snapshots_kind_version",
        "catalog_sync_snapshots",
        ["resource_kind", "snapshot_version"],
    )
    op.create_check_constraint(
        "ck_catalog_snapshots_version_positive",
        "catalog_sync_snapshots",
        "snapshot_version >= 1",
    )
    op.create_check_constraint(
        "ck_catalog_snapshots_resource_kind",
        "catalog_sync_snapshots",
        "resource_kind IN ('accounts', 'categories', 'labels', "
        "'record_rules')",
    )
    op.create_index(
        "ix_catalog_snapshots_kind_version",
        "catalog_sync_snapshots",
        ["resource_kind", "snapshot_version"],
    )

    op.create_table(
        "catalog_sync_cursors",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "resource_kind",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_remote_revision",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column(
            "current_snapshot_id",
            _uuid(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_catalog_sync_cursors_kind",
        "catalog_sync_cursors",
        ["resource_kind"],
    )
    op.create_check_constraint(
        "ck_catalog_sync_cursors_resource_kind",
        "catalog_sync_cursors",
        "resource_kind IN ('accounts', 'categories', 'labels', "
        "'record_rules')",
    )
    op.create_foreign_key(
        "fk_catalog_sync_cursors_snapshot",
        "catalog_sync_cursors",
        "catalog_sync_snapshots",
        ["current_snapshot_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_table("catalog_sync_cursors")
    op.drop_table("catalog_sync_snapshots")

"""Create account_mappings table for validated FinancialAccount-to-Wallet mapping.

Revision ID: 0008_financial_account_mapping
Revises: 0007_catalog_sync
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_financial_account_mapping"
down_revision = "0007_catalog_sync"
branch_labels = None
depends_on = None


def _uuid() -> "sa.TypeEngine[object]":
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "account_mappings",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("financial_account_id", _uuid(), nullable=False),
        sa.Column("remote_account_id", sa.String(length=255), nullable=False),
        sa.Column("validated_snapshot_id", _uuid(), nullable=False),
        sa.Column(
            "validated_snapshot_version", sa.Integer(), nullable=False
        ),
        sa.Column(
            "validated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "superseded_at", sa.DateTime(timezone=True), nullable=True
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
    op.create_foreign_key(
        "fk_account_mappings_financial_account",
        "account_mappings",
        "financial_accounts",
        ["financial_account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_account_mappings_snapshot",
        "account_mappings",
        "catalog_sync_snapshots",
        ["validated_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_account_mappings_active_one",
        "account_mappings",
        ["financial_account_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
        sqlite_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("account_mappings")

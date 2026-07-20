"""Create MCP advisory enrichment tables.

Adds three tables for the Phase A persistence contract:

* ``mcp_profile_snapshots`` — immutable cached MCP profile metadata
* ``advisory_research`` — bounded MCP evidence for candidate research
* ``enrichment_decisions`` — versioned immutable enrichment proposals

Revision ID: 0009_mcp_advisory_enrichment
Revises: 0008_financial_account_mapping
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_mcp_advisory_enrichment"
down_revision = "0008_financial_account_mapping"
branch_labels = None
depends_on = None


def _uuid() -> "sa.TypeEngine[object]":
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "mcp_profile_snapshots",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("sync_state", sa.String(32), nullable=False),
        sa.Column("granted_scopes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_limit_metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_mcp_profile_snapshots_sync_state",
        "mcp_profile_snapshots",
        "sync_state IN ('complete', 'incomplete', 'pending')",
    )

    op.create_table(
        "advisory_research",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("candidate_id", _uuid(), nullable=True),
        sa.Column("financial_event_id", _uuid(), nullable=True),
        sa.Column("evidence_grade", sa.String(32), nullable=False),
        sa.Column("profile_snapshot_id", _uuid(), nullable=True),
        sa.Column("query_inputs", postgresql.JSONB(), nullable=True),
        sa.Column("response_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=True),
        sa.Column("integrity_hash", sa.String(128), nullable=True),
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
        "fk_advisory_research_candidate",
        "advisory_research",
        "transaction_candidates",
        ["candidate_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_advisory_research_financial_event",
        "advisory_research",
        "financial_events",
        ["financial_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_advisory_research_profile_snapshot",
        "advisory_research",
        "mcp_profile_snapshots",
        ["profile_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_advisory_research_candidate_id", "advisory_research", ["candidate_id"])
    op.create_index("ix_advisory_research_financial_event_id", "advisory_research", ["financial_event_id"])
    op.create_check_constraint(
        "ck_advisory_research_one_target",
        "advisory_research",
        "(candidate_id IS NOT NULL AND financial_event_id IS NULL) "
        "OR (candidate_id IS NULL AND financial_event_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_advisory_research_evidence_grade",
        "advisory_research",
        "evidence_grade IN ("
        "'exact_recurrence', 'merchant_history', "
        "'context_only', 'no_recommendation'"
        ")",
    )

    op.create_table(
        "enrichment_decisions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("financial_event_id", _uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("evidence_grade", sa.String(32), nullable=False),
        sa.Column("selected_account_id", sa.String(255), nullable=True),
        sa.Column("selected_category_id", sa.String(255), nullable=True),
        sa.Column("selected_label_ids", postgresql.JSONB(), nullable=True),
        sa.Column("selected_payment_type", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(), nullable=True),
        sa.Column("query_inputs", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=True),
        sa.Column("catalog_snapshot_ids", postgresql.JSONB(), nullable=True),
        sa.Column("finalized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_foreign_key(
        "fk_enrichment_decisions_financial_event",
        "enrichment_decisions",
        "financial_events",
        ["financial_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_enrichment_decisions_financial_event_id",
        "enrichment_decisions",
        ["financial_event_id"],
    )
    op.create_unique_constraint(
        "uq_enrichment_decisions_event_version",
        "enrichment_decisions",
        ["financial_event_id", "version"],
    )
    op.create_check_constraint(
        "ck_enrichment_decisions_version_positive",
        "enrichment_decisions",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_enrichment_decisions_evidence_grade",
        "enrichment_decisions",
        "evidence_grade IN ("
        "'exact_recurrence', 'merchant_history', "
        "'context_only', 'no_recommendation'"
        ")",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_enrichment_decisions_one_finalized "
        "ON enrichment_decisions (financial_event_id) "
        "WHERE finalized IS TRUE"
    )


def downgrade() -> None:
    op.drop_table("enrichment_decisions")
    op.drop_table("advisory_research")
    op.drop_table("mcp_profile_snapshots")

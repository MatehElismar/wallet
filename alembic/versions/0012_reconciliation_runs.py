"""Create durable statement-evidence reconciliation runs.

Revises: 0011_pre_enrichment_proposals
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_reconciliation_runs"
down_revision = "0011_pre_enrichment_proposals"
branch_labels = None
depends_on = None


def _uuid() -> sa.TypeEngine[object]:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="materialized"),
        sa.Column("statement_account_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("included_statement_line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("undated_excluded_line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("period_start <= period_end", name="ck_reconciliation_runs_range"),
        sa.CheckConstraint("state IN ('materialized')", name="ck_reconciliation_runs_state"),
        sa.CheckConstraint("statement_account_count >= 0", name="ck_reconciliation_runs_account_count"),
        sa.CheckConstraint("included_statement_line_count >= 0", name="ck_reconciliation_runs_included_line_count"),
        sa.CheckConstraint("undated_excluded_line_count >= 0", name="ck_reconciliation_runs_undated_line_count"),
    )
    op.create_index("ix_reconciliation_runs_created_at", "reconciliation_runs", ["created_at"])

    op.create_table(
        "reconciliation_run_account_coverages",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("reconciliation_run_id", _uuid(), nullable=False),
        sa.Column("financial_account_id", _uuid(), nullable=False),
        sa.Column("issuer_snapshot", sa.String(length=128), nullable=False),
        sa.Column("external_reference_snapshot", sa.String(length=255), nullable=False),
        sa.Column("statement_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("included_line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("undated_excluded_line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unresolved_line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ambiguous_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ignored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["reconciliation_run_id"], ["reconciliation_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_account_id"], ["financial_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reconciliation_run_id", "financial_account_id", name="uq_reconciliation_run_account_coverage"),
        sa.CheckConstraint("statement_count >= 0", name="ck_reconciliation_run_coverage_statement_count"),
        sa.CheckConstraint("included_line_count >= 0", name="ck_reconciliation_run_coverage_included"),
        sa.CheckConstraint("undated_excluded_line_count >= 0", name="ck_reconciliation_run_coverage_undated"),
        sa.CheckConstraint("unresolved_line_count >= 0", name="ck_reconciliation_run_coverage_unresolved"),
        sa.CheckConstraint("new_count >= 0", name="ck_reconciliation_run_coverage_new"),
        sa.CheckConstraint("matched_count >= 0", name="ck_reconciliation_run_coverage_matched"),
        sa.CheckConstraint("ambiguous_count >= 0", name="ck_reconciliation_run_coverage_ambiguous"),
        sa.CheckConstraint("ignored_count >= 0", name="ck_reconciliation_run_coverage_ignored"),
        sa.CheckConstraint(
            "included_line_count = unresolved_line_count + new_count + matched_count + ambiguous_count + ignored_count",
            name="ck_reconciliation_run_coverage_count_equation",
        ),
    )
    op.create_index(
        "ix_reconciliation_run_account_coverages_run",
        "reconciliation_run_account_coverages",
        ["reconciliation_run_id"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_reconciliation_run_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'materialized reconciliation snapshots are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reconciliation_runs_immutable
        BEFORE UPDATE OR DELETE ON reconciliation_runs
        FOR EACH ROW EXECUTE FUNCTION reject_reconciliation_run_snapshot_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reconciliation_run_account_coverages_immutable
        BEFORE UPDATE OR DELETE ON reconciliation_run_account_coverages
        FOR EACH ROW EXECUTE FUNCTION reject_reconciliation_run_snapshot_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_reconciliation_run_account_coverages_immutable "
        "ON reconciliation_run_account_coverages"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_reconciliation_runs_immutable "
        "ON reconciliation_runs"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_reconciliation_run_snapshot_mutation()")
    op.drop_table("reconciliation_run_account_coverages")
    op.drop_table("reconciliation_runs")

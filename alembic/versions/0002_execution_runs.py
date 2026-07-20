"""Add durable execution-run traceability and integration execution modes.

Revision ID: 0002_execution_runs
Revises: 0001_initial
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_execution_runs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _uuid() -> sa.TypeEngine[object]:
    return postgresql.UUID(as_uuid=True)


def _jsonb() -> sa.TypeEngine[object]:
    return postgresql.JSONB()


def upgrade() -> None:
    op.create_table(
        "execution_runs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("initiator", sa.String(length=128), nullable=True),
        sa.Column("metadata", _jsonb(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_summary", sa.String(length=2048), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("mode IN ('disabled', 'dry_run', 'live')", name="ck_execution_runs_mode"),
        sa.CheckConstraint("trigger IN ('manual', 'scheduled', 'test')", name="ck_execution_runs_trigger"),
        sa.CheckConstraint("outcome IN ('running', 'succeeded', 'failed', 'cancelled')", name="ck_execution_runs_outcome"),
    )
    op.create_index("ix_execution_runs_started_at", "execution_runs", ["started_at"])
    op.create_index("ix_execution_runs_mode_trigger", "execution_runs", ["mode", "trigger"])

    tables = (
        "source_messages",
        "processing_attempts",
        "import_commands",
        "wallet_attempts",
        "audit_events",
    )
    for table in tables:
        op.add_column(table, sa.Column("execution_run_id", _uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_execution_run",
            table,
            "execution_runs",
            ["execution_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_execution_run", table, ["execution_run_id"])


def downgrade() -> None:
    tables = (
        "audit_events",
        "wallet_attempts",
        "import_commands",
        "processing_attempts",
        "source_messages",
    )
    for table in tables:
        op.drop_index(f"ix_{table}_execution_run", table_name=table)
        op.drop_constraint(f"fk_{table}_execution_run", table, type_="foreignkey")
        op.drop_column(table, "execution_run_id")

    op.drop_index("ix_execution_runs_mode_trigger", table_name="execution_runs")
    op.drop_index("ix_execution_runs_started_at", table_name="execution_runs")
    op.drop_table("execution_runs")

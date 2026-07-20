"""Protect statement identity and preserve reversal evidence.

Revision ID: 0005_reconciliation_integrity
Revises: 0004_statement_reconciliation
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_reconciliation_integrity"
down_revision = "0004_statement_reconciliation"
branch_labels = None
depends_on = None


def _uuid() -> sa.TypeEngine[object]:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_statements_account_document_fingerprint",
        "bank_statements",
        ["account_id", "document_fingerprint"],
    )
    op.add_column(
        "bank_statement_lines",
        sa.Column(
            "event_status",
            sa.String(length=16),
            nullable=False,
            server_default="posted",
        ),
    )
    op.add_column(
        "bank_statement_lines",
        sa.Column("related_reference", sa.String(length=255), nullable=True),
    )
    op.create_check_constraint(
        "ck_statement_lines_event_status",
        "bank_statement_lines",
        "event_status IN ('posted', 'reversed', 'cancelled')",
    )
    op.add_column(
        "financial_events",
        sa.Column("reverses_event_id", _uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_financial_events_reverses_event",
        "financial_events",
        "financial_events",
        ["reverses_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_financial_events_reverses_event",
        "financial_events",
        ["reverses_event_id"],
    )
    op.drop_constraint(
        "ck_statement_review_batches_state",
        "statement_review_batches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_statement_review_batches_state",
        "statement_review_batches",
        "state IN ('open', 'approved', 'rejected', 'superseded')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_statement_review_batches_state",
        "statement_review_batches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_statement_review_batches_state",
        "statement_review_batches",
        "state IN ('open', 'approved', 'rejected')",
    )
    op.drop_index("ix_financial_events_reverses_event", table_name="financial_events")
    op.drop_constraint(
        "fk_financial_events_reverses_event",
        "financial_events",
        type_="foreignkey",
    )
    op.drop_column("financial_events", "reverses_event_id")
    op.drop_constraint(
        "ck_statement_lines_event_status",
        "bank_statement_lines",
        type_="check",
    )
    op.drop_column("bank_statement_lines", "related_reference")
    op.drop_column("bank_statement_lines", "event_status")
    op.drop_constraint(
        "uq_statements_account_document_fingerprint",
        "bank_statements",
        type_="unique",
    )

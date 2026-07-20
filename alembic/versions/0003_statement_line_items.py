"""Allow multiple independently versioned candidates per source message.

Revision ID: 0003_statement_line_items
Revises: 0002_execution_runs
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_statement_line_items"
down_revision = "0002_execution_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transaction_candidates",
        sa.Column("source_item_index", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE transaction_candidates SET source_item_index = 1")
    op.alter_column("transaction_candidates", "source_item_index", nullable=False)
    op.drop_constraint(
        "uq_candidates_source_message_version",
        "transaction_candidates",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_candidates_source_item_version",
        "transaction_candidates",
        ["source_message_id", "source_item_index", "candidate_version"],
    )
    op.create_check_constraint(
        "ck_candidates_source_item_positive",
        "transaction_candidates",
        "source_item_index >= 1",
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0003_statement_line_items is intentionally non-reversible: "
        "independent line-item version sequences can collide under the old "
        "(source_message_id, candidate_version) uniqueness contract."
    )

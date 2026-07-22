"""Pre-enrichment proposals tied to statement lines.

Allows enrichment decisions to be generated and stored for statement lines
before batch approval.

Revises: 0010_enrich_op_override
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_pre_enrichment_proposals"
down_revision = "0010_enrich_op_override"
branch_labels = None
depends_on = None


def _uuid() -> sa.TypeEngine[object]:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # 1. Add statement_line_id column to enrichment_decisions (nullable initially)
    op.add_column(
        "enrichment_decisions",
        sa.Column("statement_line_id", _uuid(), nullable=True),
    )

    # 2. Make financial_event_id nullable
    op.alter_column(
        "enrichment_decisions",
        "financial_event_id",
        existing_type=_uuid(),
        nullable=True,
    )

    # 3. Populate statement_line_id for existing rows from financial_events table
    op.execute(
        "UPDATE enrichment_decisions "
        "SET statement_line_id = ("
        "  SELECT statement_line_id "
        "  FROM financial_events "
        "  WHERE financial_events.id = enrichment_decisions.financial_event_id"
        ")"
    )

    # 4. Set statement_line_id to NOT NULL
    op.alter_column(
        "enrichment_decisions",
        "statement_line_id",
        existing_type=_uuid(),
        nullable=False,
    )

    # 5. Add foreign key for statement_line_id
    op.create_foreign_key(
        "fk_enrichment_decisions_statement_line",
        "enrichment_decisions",
        "bank_statement_lines",
        ["statement_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 6. Add index on statement_line_id
    op.create_index(
        "ix_enrichment_decisions_statement_line_id",
        "enrichment_decisions",
        ["statement_line_id"],
    )

    # 7. Drop old unique constraint (financial_event_id, version) and index
    op.drop_constraint(
        "uq_enrichment_decisions_event_version",
        "enrichment_decisions",
        type_="unique",
    )
    op.execute("DROP INDEX IF EXISTS uq_enrichment_decisions_one_finalized")

    # 8. Create new unique constraint (statement_line_id, version)
    op.create_unique_constraint(
        "uq_enrichment_decisions_line_version",
        "enrichment_decisions",
        ["statement_line_id", "version"],
    )

    # 9. Create partial unique index for finalized decisions per statement_line_id
    op.execute(
        "CREATE UNIQUE INDEX uq_enrichment_decisions_one_finalized "
        "ON enrichment_decisions (statement_line_id) "
        "WHERE finalized IS TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_enrichment_decisions_one_finalized")
    op.drop_constraint(
        "uq_enrichment_decisions_line_version",
        "enrichment_decisions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_enrichment_decisions_event_version",
        "enrichment_decisions",
        ["financial_event_id", "version"],
    )
    op.create_index(
        "ix_enrichment_decisions_financial_event_id",
        "enrichment_decisions",
        ["financial_event_id"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_enrichment_decisions_one_finalized "
        "ON enrichment_decisions (financial_event_id) "
        "WHERE finalized IS TRUE"
    )

    op.drop_index(
        "ix_enrichment_decisions_statement_line_id",
        "enrichment_decisions",
    )
    op.drop_constraint(
        "fk_enrichment_decisions_statement_line",
        "enrichment_decisions",
        type_="foreignkey",
    )
    op.alter_column(
        "enrichment_decisions",
        "financial_event_id",
        existing_type=_uuid(),
        nullable=False,
    )
    op.drop_column("enrichment_decisions", "statement_line_id")

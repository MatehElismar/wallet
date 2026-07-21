"""Allow operator_override evidence grade for enrichment decisions.

Extends the ``evidence_grade`` CHECK constraints on ``advisory_research`` and
``enrichment_decisions`` to admit the new ``operator_override`` grade used by
Phase C explicit operator overrides. A decision with this grade is
finalizable (validated against the current REST catalog snapshots) but, like
every enrichment row, is never written to Wallet from this surface.

Revision ID: 0010_enrich_op_override
Revises: 0009_mcp_advisory_enrichment
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_enrich_op_override"
down_revision = "0009_mcp_advisory_enrichment"
branch_labels = None
depends_on = None

_GRADE_LIST = (
    "'exact_recurrence', 'merchant_history', "
    "'context_only', 'no_recommendation', "
    "'operator_override'"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_advisory_research_evidence_grade",
        "advisory_research",
        type_="check",
    )
    op.create_check_constraint(
        "ck_advisory_research_evidence_grade",
        "advisory_research",
        f"evidence_grade IN ({_GRADE_LIST})",
    )
    op.drop_constraint(
        "ck_enrichment_decisions_evidence_grade",
        "enrichment_decisions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enrichment_decisions_evidence_grade",
        "enrichment_decisions",
        f"evidence_grade IN ({_GRADE_LIST})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_enrichment_decisions_evidence_grade",
        "enrichment_decisions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enrichment_decisions_evidence_grade",
        "enrichment_decisions",
        "evidence_grade IN ("
        "'exact_recurrence', 'merchant_history', "
        "'context_only', 'no_recommendation'"
        ")",
    )
    op.drop_constraint(
        "ck_advisory_research_evidence_grade",
        "advisory_research",
        type_="check",
    )
    op.create_check_constraint(
        "ck_advisory_research_evidence_grade",
        "advisory_research",
        "evidence_grade IN ("
        "'exact_recurrence', 'merchant_history', "
        "'context_only', 'no_recommendation'"
        ")",
    )

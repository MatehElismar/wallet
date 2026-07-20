"""Add statement reconciliation and canonical financial events.

Revision ID: 0004_statement_reconciliation
Revises: 0003_statement_line_items
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_statement_reconciliation"
down_revision = "0003_statement_line_items"
branch_labels = None
depends_on = None


def _uuid() -> sa.TypeEngine[object]:
    return postgresql.UUID(as_uuid=True)


def _timestamps(*, mutable: bool) -> list[sa.Column[object]]:
    columns = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    ]
    if mutable:
        columns.append(
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), nullable=False,
                server_default=sa.text("now()"),
            )
        )
    return columns


def upgrade() -> None:
    op.create_table(
        "financial_accounts",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("issuer", sa.String(length=128), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=False),
        sa.Column("wallet_account_reference", sa.String(length=255), nullable=True),
        *_timestamps(mutable=True),
        sa.UniqueConstraint(
            "issuer", "external_reference",
            name="uq_financial_accounts_issuer_external",
        ),
    )
    op.create_table(
        "bank_statements",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_message_id", _uuid(), nullable=False),
        sa.Column("processing_attempt_id", _uuid(), nullable=False),
        sa.Column("account_id", _uuid(), nullable=False),
        sa.Column("statement_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("document_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("statement_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("opening_balance_minor", sa.BigInteger(), nullable=True),
        sa.Column("closing_balance_minor", sa.BigInteger(), nullable=True),
        *_timestamps(mutable=True),
        sa.ForeignKeyConstraint(["source_message_id"], ["source_messages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["processing_attempt_id"], ["processing_attempts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["financial_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("source_message_id", "statement_version", name="uq_statements_source_version"),
        sa.CheckConstraint("statement_version >= 1", name="ck_statements_version_positive"),
        sa.CheckConstraint(
            "status IN ('open', 'approved', 'rejected', 'superseded')",
            name="ck_statements_status",
        ),
    )
    op.create_table(
        "bank_statement_lines",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("statement_id", _uuid(), nullable=False),
        sa.Column("line_index", sa.Integer(), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("line_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("posting_date", sa.Date(), nullable=True),
        sa.Column("running_balance_minor", sa.BigInteger(), nullable=True),
        *_timestamps(mutable=False),
        sa.ForeignKeyConstraint(["statement_id"], ["bank_statements.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("statement_id", "line_index", name="uq_statement_lines_statement_index"),
        sa.CheckConstraint("line_index >= 1", name="ck_statement_lines_index_positive"),
        sa.CheckConstraint("amount_minor > 0", name="ck_statement_lines_amount_positive"),
        sa.CheckConstraint(
            "length(currency) = 3 "
            "AND substr(currency, 1, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(currency, 2, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(currency, 3, 1) BETWEEN 'A' AND 'Z'",
            name="ck_statement_lines_currency_format",
        ),
    )
    op.create_index("ix_statement_lines_fingerprint", "bank_statement_lines", ["line_fingerprint"])
    op.create_table(
        "transaction_observations",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_message_id", _uuid(), nullable=False),
        sa.Column("processing_attempt_id", _uuid(), nullable=False),
        sa.Column("account_id", _uuid(), nullable=True),
        sa.Column("candidate_id", _uuid(), nullable=False),
        sa.Column("source_item_index", sa.Integer(), nullable=False),
        sa.Column("observation_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        *_timestamps(mutable=False),
        sa.ForeignKeyConstraint(["source_message_id"], ["source_messages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["processing_attempt_id"], ["processing_attempts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["financial_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_id"], ["transaction_candidates.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("source_message_id", "source_item_index", "observation_version", name="uq_observations_source_item_version"),
        sa.UniqueConstraint("candidate_id", name="uq_observations_candidate_one"),
        sa.CheckConstraint("observation_version >= 1", name="ck_observations_version_positive"),
        sa.CheckConstraint("source_item_index >= 1", name="ck_observations_index_positive"),
        sa.CheckConstraint("amount_minor > 0", name="ck_observations_amount_positive"),
        sa.CheckConstraint(
            "status IN ('provisional', 'confirmed', 'rejected', 'superseded')",
            name="ck_observations_status",
        ),
    )
    op.create_index(
        "ix_observations_match", "transaction_observations",
        ["amount_minor", "currency", "direction", "transaction_date"],
    )
    op.create_table(
        "statement_review_batches",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("statement_id", _uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reviewer_id", sa.String(length=128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=1024), nullable=True),
        *_timestamps(mutable=True),
        sa.ForeignKeyConstraint(["statement_id"], ["bank_statements.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("statement_id", name="uq_statement_review_batches_statement_one"),
        sa.CheckConstraint("state IN ('open', 'approved', 'rejected')", name="ck_statement_review_batches_state"),
    )
    op.create_table(
        "reconciliation_links",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("statement_line_id", _uuid(), nullable=False),
        sa.Column("observation_id", _uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("note", sa.String(length=1024), nullable=True),
        *_timestamps(mutable=True),
        sa.ForeignKeyConstraint(["statement_line_id"], ["bank_statement_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observation_id"], ["transaction_observations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("statement_line_id", name="uq_reconciliation_line_one"),
        sa.UniqueConstraint("observation_id", name="uq_reconciliation_observation_one"),
        sa.CheckConstraint("outcome IN ('new', 'matched', 'ambiguous', 'ignored')", name="ck_reconciliation_outcome"),
        sa.CheckConstraint("method IN ('exact_reference', 'exact_details', 'manual', 'none')", name="ck_reconciliation_method"),
    )
    op.create_table(
        "financial_events",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("account_id", _uuid(), nullable=False),
        sa.Column("statement_line_id", _uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("posting_date", sa.Date(), nullable=True),
        *_timestamps(mutable=False),
        sa.ForeignKeyConstraint(["account_id"], ["financial_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["statement_line_id"], ["bank_statement_lines.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("statement_line_id", name="uq_financial_events_statement_line_one"),
        sa.CheckConstraint("status IN ('posted', 'reversed', 'cancelled')", name="ck_financial_events_status"),
        sa.CheckConstraint("amount_minor > 0", name="ck_financial_events_amount_positive"),
    )
    op.create_index("ix_financial_events_account_posting", "financial_events", ["account_id", "posting_date"])

    op.add_column("import_commands", sa.Column("financial_event_id", _uuid(), nullable=True))
    op.alter_column("import_commands", "candidate_id", existing_type=_uuid(), nullable=True)
    op.create_foreign_key(
        "fk_import_commands_financial_event",
        "import_commands",
        "financial_events",
        ["financial_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_import_commands_financial_event_one",
        "import_commands",
        ["financial_event_id"],
    )
    op.create_check_constraint(
        "ck_import_commands_one_origin",
        "import_commands",
        "(candidate_id IS NOT NULL AND financial_event_id IS NULL) "
        "OR (candidate_id IS NULL AND financial_event_id IS NOT NULL)",
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0004_statement_reconciliation is intentionally non-reversible: "
        "event-origin import commands cannot be represented by the prior "
        "candidate-only schema without losing financial evidence."
    )

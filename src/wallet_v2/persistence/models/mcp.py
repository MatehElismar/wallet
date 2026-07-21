"""MCP advisory enrichment persistence models.

Three tables implement the Phase A persistence contract:

* :class:`McpProfileSnapshot` — cached profile metadata (sync state, scopes,
  rate-limit info) from the most recent ``get_client_profile`` call.
* :class:`AdvisoryResearch` — bounded evidence from MCP queries for
  exactly one of a notification ``TransactionCandidate`` (candidate research
  preview) or a statement-confirmed ``FinancialEvent`` (event research).
* :class:`EnrichmentDecision` — a versioned, immutable enrichment proposal
  for a statement-confirmed ``FinancialEvent``. Only one finalized decision
  may exist per financial event, enforced at the database layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_v2.persistence.base import Base, Immutable, Timestamped
from wallet_v2.persistence.types import JSONB

if TYPE_CHECKING:
    from wallet_v2.persistence.models.candidate import TransactionCandidate
    from wallet_v2.persistence.models.reconciliation import FinancialEvent


class McpProfileSnapshot(Base, Immutable):
    """Immutable cached MCP client profile metadata.

    Each row captures the sync state, granted scopes, sync timestamp, and
    rate-limit metadata observed in one ``get_client_profile`` response.
    Rows are append-only so the application can audit profile state changes
    over time.
    """

    __tablename__ = "mcp_profile_snapshots"
    __table_args__ = (
        CheckConstraint(
            "sync_state IN ('complete', 'incomplete', 'pending')",
            name="ck_mcp_profile_snapshots_sync_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sync_state: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_scopes: Mapped[list[str]] = mapped_column(
        JSONB(), nullable=False, default=list
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rate_limit_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )


class AdvisoryResearch(Base, Timestamped):
    """Bounded MCP evidence captured for a notification candidate or event.

    Targets exactly one of ``TransactionCandidate`` (candidate research
    preview) or ``FinancialEvent`` (event research), enforced at the
    database layer by a CHECK constraint.

    Stores query inputs, response metadata, selected evidence record
    identifiers, and an integrity hash rather than unbounded raw history.
    """

    __tablename__ = "advisory_research"
    __table_args__ = (
        CheckConstraint(
            "(candidate_id IS NOT NULL AND financial_event_id IS NULL) "
            "OR (candidate_id IS NULL AND financial_event_id IS NOT NULL)",
            name="ck_advisory_research_one_target",
        ),
        CheckConstraint(
            "evidence_grade IN ("
            "'exact_recurrence', 'merchant_history', "
            "'context_only', 'no_recommendation', "
            "'operator_override'"
            ")",
            name="ck_advisory_research_evidence_grade",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transaction_candidates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    financial_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("financial_events.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    evidence_grade: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_profile_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    query_inputs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    response_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    evidence_ids: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    integrity_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    candidate: Mapped["TransactionCandidate | None"] = relationship(
        foreign_keys=[candidate_id],
    )
    financial_event: Mapped["FinancialEvent | None"] = relationship(
        foreign_keys=[financial_event_id],
    )
    profile_snapshot: Mapped["McpProfileSnapshot | None"] = relationship(
        foreign_keys=[profile_snapshot_id],
    )


class EnrichmentDecision(Base, Immutable):
    """A versioned, immutable enrichment proposal for a canonical event.

    One ``FinancialEvent`` may have multiple proposal versions (inserted
    on re-enrichment). Only one row may have ``finalized=True`` per event,
    enforced by a PostgreSQL partial unique index.
    """

    __tablename__ = "enrichment_decisions"
    __table_args__ = (
        UniqueConstraint(
            "financial_event_id",
            "version",
            name="uq_enrichment_decisions_event_version",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_enrichment_decisions_version_positive",
        ),
        CheckConstraint(
            "evidence_grade IN ("
            "'exact_recurrence', 'merchant_history', "
            "'context_only', 'no_recommendation', "
            "'operator_override'"
            ")",
            name="ck_enrichment_decisions_evidence_grade",
        ),
        Index(
            "uq_enrichment_decisions_one_finalized",
            "financial_event_id",
            unique=True,
            postgresql_where="finalized IS TRUE",
            sqlite_where=text("finalized IS TRUE"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    financial_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("financial_events.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(32), nullable=False)
    selected_account_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    selected_category_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    selected_label_ids: Mapped[list[str] | None] = mapped_column(
        JSONB(), nullable=True
    )
    selected_payment_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    query_inputs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    evidence_refs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    catalog_snapshot_ids: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    finalized: Mapped[bool] = mapped_column(nullable=False, default=False)

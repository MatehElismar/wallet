"""Durable identity for a single application execution.

Every operator, scheduled, and integration-test invocation receives an
``ExecutionRun``. Workflow records refer to that run so dry-run activity is
distinguishable from live work without encoding environment-specific markers in
business identifiers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from wallet_v2.domain.enums import IntegrationMode
from wallet_v2.persistence.base import Base, Timestamped
from wallet_v2.persistence.types import JSONB


class ExecutionRun(Base, Timestamped):
    """One manually, scheduled, or test-triggered execution.

    ``metadata_json`` is intentionally limited to a redacted operational snapshot:
    it may identify adapter versions and selected modes but must never contain
    passwords, API keys, complete email bodies, or provider responses.
    """

    __tablename__ = "execution_runs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('disabled', 'dry_run', 'live')",
            name="ck_execution_runs_mode",
        ),
        CheckConstraint(
            "trigger IN ('manual', 'scheduled', 'test')",
            name="ck_execution_runs_trigger",
        ),
        CheckConstraint(
            "outcome IN ('running', 'succeeded', 'failed', 'cancelled')",
            name="ck_execution_runs_outcome",
        ),
        Index("ix_execution_runs_started_at", "started_at"),
        Index("ix_execution_runs_mode_trigger", "mode", "trigger"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    mode: Mapped[IntegrationMode] = mapped_column(String(16), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    initiator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB(), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running"
    )
    error_summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)

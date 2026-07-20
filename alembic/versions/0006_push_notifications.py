"""Create push notification subscription and outbox tables.

Revision ID: 0006_push_notifications
Revises: 0005_reconciliation_integrity
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_push_notifications"
down_revision = "0005_reconciliation_integrity"
branch_labels = None
depends_on = None


def _uuid() -> "sa.TypeEngine[object]":
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "endpoint",
            sa.String(length=1024),
            nullable=False,
        ),
        sa.Column("keys_p256dh", sa.Text(), nullable=False),
        sa.Column("keys_auth", sa.Text(), nullable=False),
        sa.Column(
            "user_agent",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "disabled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "disabled_reason",
            sa.String(length=255),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            "endpoint",
            name="uq_push_subscriptions_endpoint",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'expired')",
            name="ck_push_subscriptions_status",
        ),
    )

    op.create_table(
        "notification_outbox",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            _uuid(),
            sa.ForeignKey(
                "push_subscriptions.id",
                ondelete="RESTRICT",
                name="fk_notification_outbox_subscription",
            ),
            nullable=False,
        ),
        sa.Column(
            "intent_kind",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "entity_kind",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "payload_metadata",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "provider_message_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "last_error_kind",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "last_error_message",
            sa.Text(),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            "idempotency_key",
            "subscription_id",
            name="uq_notification_outbox_idempotency_key_subscription",
        ),
        sa.Index(
            "ix_notification_outbox_pending",
            "status",
            "created_at",
            postgresql_using="btree",
        ),
        sa.Index(
            "ix_notification_outbox_subscription",
            "subscription_id",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'delivered', 'failed', 'stale')",
            name="ck_notification_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_notification_outbox_attempt_count",
        ),
        sa.CheckConstraint(
            "max_attempts >= 1",
            name="ck_notification_outbox_max_attempts",
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_outbox")
    op.drop_table("push_subscriptions")

"""Typed identifiers for the Wallet V2 pipeline.

These are ``NewType`` aliases over :class:`uuid.UUID` so the domain layer can
distinguish, at static-analysis time, a ``SourceMessageId`` from a
``CandidateId``. At runtime they are plain :class:`uuid.UUID` values.

SQLAlchemy columns use ``uuid.UUID`` directly; these aliases exist for the
domain/service layer that will be built on top of the foundation.
"""

from __future__ import annotations

from typing import NewType
from uuid import UUID, uuid4

InboxId = NewType("InboxId", UUID)
SourceMessageId = NewType("SourceMessageId", UUID)
AttemptId = NewType("AttemptId", UUID)
CandidateId = NewType("CandidateId", UUID)
ReviewTaskId = NewType("ReviewTaskId", UUID)
ImportCommandId = NewType("ImportCommandId", UUID)
WalletAttemptId = NewType("WalletAttemptId", UUID)
ReceiptId = NewType("ReceiptId", UUID)


def new_inbox_id() -> InboxId:
    return InboxId(uuid4())


def new_source_message_id() -> SourceMessageId:
    return SourceMessageId(uuid4())


def new_attempt_id() -> AttemptId:
    return AttemptId(uuid4())


def new_candidate_id() -> CandidateId:
    return CandidateId(uuid4())


def new_review_task_id() -> ReviewTaskId:
    return ReviewTaskId(uuid4())


def new_import_command_id() -> ImportCommandId:
    return ImportCommandId(uuid4())


def new_wallet_attempt_id() -> WalletAttemptId:
    return WalletAttemptId(uuid4())


def new_receipt_id() -> ReceiptId:
    return ReceiptId(uuid4())


SubscriptionId = NewType("SubscriptionId", UUID)
NotificationOutboxId = NewType("NotificationOutboxId", UUID)


def new_subscription_id() -> SubscriptionId:
    return SubscriptionId(uuid4())


def new_notification_outbox_id() -> NotificationOutboxId:
    return NotificationOutboxId(uuid4())

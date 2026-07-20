"""Domain value objects for the push notification pipeline.

These are pure data objects with no persistence or I/O dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NotificationIntent:
    """A request to notify the operator about a reconciliation event.

    The ``idempotency_key`` ensures that repeated processing of the same
    domain event does not create duplicate outbox records. The key is derived
    from the event kind and entity identity that triggered the notification.
    """

    idempotency_key: str
    kind: str
    title: str
    body: str
    entity_kind: str
    entity_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PushSubscriptionData:
    """The browser Push API credential bundle submitted by the client."""

    endpoint: str
    keys_p256dh: str
    keys_auth: str
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Outcome of a push delivery attempt."""

    success: bool
    provider_message_id: str | None = None
    error_kind: str | None = None
    error_message: str | None = None
    subscription_disabled: bool = False

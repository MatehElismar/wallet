"""Push provider adapter.

The live provider is a stub that **fails closed** — it never delivers a
message unless explicitly configured to succeed in tests. This preserves the
fail-closed contract: the console defaults to disabled push and the provider
raises on any real send attempt, ensuring that no notification is silently
dropped without the deployment having provisioned keys.

Tests inject a mock provider that implements the same :class:`PushProvider`
protocol.
"""

from __future__ import annotations

from wallet_v2.application.contracts import PushDeliveryResult, PushMessage, PushProvider


class DisabledPushProvider(PushProvider):
    """Push provider stub that fails closed on every send attempt.

    This is the production default when no VAPID/FCM credentials are
    provisioned. All sends raise a :class:`RuntimeError` so that callers
    cannot mistake a silent no-op for a successful delivery.
    """

    def send(self, message: PushMessage) -> PushDeliveryResult:
        raise RuntimeError(
            "Push notifications are disabled: no provider credentials "
            "have been provisioned. Configure VAPID keys or FCM credentials "
            "before enabling push delivery."
        )


class StubPushProvider(PushProvider):
    """Programmable provider for testing — succeeds or fails per call.

    The ``outcomes`` list is consumed FIFO. After exhaustion, subsequent
    calls return a generic success result.
    """

    def __init__(self, outcomes: list[PushDeliveryResult] | None = None):
        self._outcomes = list(outcomes or [])
        self._call_count = 0

    def send(self, message: PushMessage) -> PushDeliveryResult:
        self._call_count += 1
        if self._outcomes:
            return self._outcomes.pop(0)
        return PushDeliveryResult(
            success=True,
            provider_message_id=f"msg-{self._call_count:06d}",
        )

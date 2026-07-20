"""BudgetBakers Wallet API adapter with explicit result classification."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from wallet_v2.application.contracts import WalletSubmissionResult
from wallet_v2.domain.enums import WalletAttemptStatus


class BudgetBakersWalletClient:
    """Submit one record to the legacy-compatible ``/v1/api/records`` route.

    This client is intentionally used only by a live application run. Dry-run
    behavior is enforced by the application service before this method can be
    called, so there is no hidden network fallback here.
    """

    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def submit(
        self, *, idempotency_key: str, payload: dict[str, object]
    ) -> WalletSubmissionResult:
        request_payload = [payload]
        body = json.dumps(request_payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/v1/api/records",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310 -- configured endpoint
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
                provider_id = self._provider_transaction_id(data)
                return WalletSubmissionResult(
                    status=WalletAttemptStatus.ACKNOWLEDGED,
                    request=payload,
                    response=data if isinstance(data, dict) else {"results": data},
                    provider_transaction_id=provider_id,
                )
        except HTTPError as exc:
            return WalletSubmissionResult(
                status=WalletAttemptStatus.FAILED,
                request=payload,
                response=None,
                error_kind=f"http_{exc.code}",
                error_message=exc.read().decode("utf-8", errors="replace")[:2048],
            )
        except TimeoutError:
            return WalletSubmissionResult(
                status=WalletAttemptStatus.UNKNOWN,
                request=payload,
                response=None,
                error_kind="timeout",
                error_message="Wallet request timed out; reconciliation required",
            )
        except URLError as exc:
            return WalletSubmissionResult(
                status=WalletAttemptStatus.UNKNOWN,
                request=payload,
                response=None,
                error_kind="network",
                error_message=str(exc.reason)[:2048],
            )

    @staticmethod
    def _provider_transaction_id(data: object) -> str | None:
        first = data[0] if isinstance(data, list) and data else data
        if not isinstance(first, dict):
            return None
        for key in ("id", "recordId", "transactionId"):
            value = first.get(key)
            if value is not None:
                return str(value)
        return None

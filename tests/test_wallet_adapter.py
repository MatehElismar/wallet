"""Wallet adapter request classification tests with no network access."""

from __future__ import annotations

from unittest.mock import patch

from wallet_v2.adapters.wallet_api import BudgetBakersWalletClient
from wallet_v2.domain.enums import WalletAttemptStatus


def test_wallet_request_carries_idempotency_key_and_acknowledges_response() -> None:
    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'[{"recordId":"record-1"}]'

    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_Response()) as open_url:
        result = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        ).submit(idempotency_key="idem-123", payload={"amount": 123})

    request = open_url.call_args.args[0]
    assert request.full_url == "https://wallet.example.test/v1/api/records"
    assert request.get_header("Idempotency-key") == "idem-123"
    assert result.status is WalletAttemptStatus.ACKNOWLEDGED
    assert result.provider_transaction_id == "record-1"


def test_wallet_timeout_is_unknown_for_reconciliation() -> None:
    with patch("wallet_v2.adapters.wallet_api.urlopen", side_effect=TimeoutError):
        result = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        ).submit(idempotency_key="idem-123", payload={"amount": 123})

    assert result.status is WalletAttemptStatus.UNKNOWN
    assert result.error_kind == "timeout"

"""Provider-selection tests for the shared OpenAI-compatible extractor."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wallet_v2.adapters.openai_compatible_llm import OpenAICompatibleExtractor
from wallet_v2.application.contracts import MailboxMessage


@pytest.mark.parametrize(
    ("provider", "expected_base_url"),
    [
        ("openai", "https://api.openai.com/v1"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
        ("deepseek", "https://api.deepseek.com/v1"),
    ],
)
def test_builtin_provider_aliases_use_openai_compatible_endpoints(
    provider: str, expected_base_url: str
) -> None:
    extractor = OpenAICompatibleExtractor(
        provider=provider,
        model="test-model",
        api_key="test-key",
        timeout_seconds=1,
    )

    assert extractor.base_url == expected_base_url


def test_custom_compatible_provider_requires_explicit_endpoint() -> None:
    with pytest.raises(ValueError, match="explicit base_url"):
        OpenAICompatibleExtractor(
            provider="glm",
            model="test-model",
            api_key="test-key",
            timeout_seconds=1,
        )


def test_gemini_alias_builds_compatible_chat_completion_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        def read(self) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"is_transaction\\":false}"}}]}'
            )

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    captured: dict[str, object] = {}

    def _urlopen(request: object, *, timeout: float) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("wallet_v2.adapters.openai_compatible_llm.urlopen", _urlopen)
    extractor = OpenAICompatibleExtractor(
        provider="gemini", model="gemini-test", api_key="key", timeout_seconds=7
    )
    result = extractor.extract(
        MailboxMessage(
            provider="imap",
            account_fingerprint="a" * 64,
            folder="INBOX",
            uid_validity=1,
            message_uid=1,
            sender="sender@example.test",
            recipient=None,
            subject="Subject",
            message_id_header=None,
            received_at=datetime.now(timezone.utc),
            body_text="Body",
        )
    )

    request = captured["request"]
    assert getattr(request, "full_url") == (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert captured["timeout"] == 7
    assert result.is_transaction is False


def test_dominican_peso_alias_is_normalized_to_iso_code() -> None:
    extractor = OpenAICompatibleExtractor(
        provider="gemini", model="gemini-test", api_key="key", timeout_seconds=7
    )

    result = extractor._parse(
        {
            "is_transaction": True,
            "transactions": [{
                "direction": "debit",
                "amount_minor": 120000,
                "currency": "RD$",
                "merchant": "Example merchant",
                "reference": None,
                "transaction_date": "2026-07-19",
            }],
        },
        {},
    )

    assert result.transaction is not None
    assert result.transaction.currency == "DOP"


def test_statement_response_preserves_each_line_item() -> None:
    extractor = OpenAICompatibleExtractor(
        provider="gemini", model="gemini-test", api_key="key", timeout_seconds=7
    )
    result = extractor._parse(
        {
            "is_transaction": True,
            "transactions": [
                {"direction": "debit", "amount_minor": 100, "currency": "DOP", "merchant": "One", "reference": None, "transaction_date": "2026-07-01"},
                {"direction": "credit", "amount_minor": 200, "currency": "DOP", "merchant": "Two", "reference": None, "transaction_date": "2026-07-02"},
            ],
        },
        {},
    )

    assert [transaction.merchant for transaction in result.transactions] == ["One", "Two"]

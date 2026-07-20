"""Wallet adapter request classification tests with no network access."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from wallet_v2.adapters.wallet_api import BudgetBakersWalletClient
from wallet_v2.application.contracts import (
    BatchCreateResult,
    CreateRecordResponseItem,
)
from wallet_v2.domain.enums import WalletAttemptStatus


# ── legacy submit-preservation tests ───────────────────────────────────


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


def test_wallet_http_error_is_failed() -> None:
    from urllib.error import HTTPError

    http_error = HTTPError(
        url="https://wallet.example.test/v1/api/records",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=None,
    )

    with patch("wallet_v2.adapters.wallet_api.urlopen", side_effect=http_error):
        result = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        ).submit(idempotency_key="idem-123", payload={"amount": 123})

    assert result.status is WalletAttemptStatus.FAILED
    assert result.error_kind == "http_400"


# ── batch create result parsing (static, no network) ──────────────────


def test_parse_flat_list_yields_per_index_results() -> None:
    raw: list[dict[str, object]] = [
        {"id": "r1", "recordId": "r1"},
        {"id": "r2", "recordId": "r2"},
    ]
    result = BudgetBakersWalletClient.parse_batch_create_response(
        raw_response=raw
    )
    assert result.all_succeeded
    assert len(result.items) == 2
    assert result.items[0].record_id == "r1"
    assert result.items[0].index == 0
    assert result.items[1].record_id == "r2"
    assert result.items[1].index == 1


def test_parse_207_mixed_result() -> None:
    raw: list[dict[str, object]] = [
        {
            "results": [
                {"index": 0, "status": 200, "record": {"recordId": "ok"}},
                {"index": 1, "status": 422, "error": {"code": "INVALID", "message": "bad"}},
            ]
        }
    ]
    result = BudgetBakersWalletClient.parse_batch_create_response(
        raw_response=raw
    )
    assert not result.all_succeeded
    assert result.succeeded_ids == ("ok",)
    assert result.failed_indices == (1,)


def test_parse_empty_response_is_empty() -> None:
    result = BudgetBakersWalletClient.parse_batch_create_response(raw_response=[])
    assert len(result.items) == 0


# ── rate-limit classification (static) ────────────────────────────────


def test_classify_429_as_rate_limit() -> None:
    assert BudgetBakersWalletClient.classify_rate_limit(status_code=429) == "rate_limit"


def test_classify_body_error_code() -> None:
    assert (
        BudgetBakersWalletClient.classify_rate_limit(
            response_body={"error": {"code": "RATE_LIMIT_EXCEEDED"}},
            status_code=400,
        )
        == "rate_limit"
    )


def test_classify_200_is_not_rate_limit() -> None:
    assert BudgetBakersWalletClient.classify_rate_limit(status_code=200) is None


def test_classify_none_body_is_none() -> None:
    assert BudgetBakersWalletClient.classify_rate_limit(status_code=400) is None


# ── read operation fixtures (GET mock through urlopen patching) ───────


def _mock_urlopen_for_get(response_body: bytes) -> object:
    class _Response:
        def __enter__(self) -> "_Response":
            return self
        def __exit__(self, *args: object) -> None:
            return None
        def read(self) -> bytes:
            return response_body
        @property
        def headers(self) -> dict[str, str]:
            return {}
    return _Response()


def test_get_accounts_parses_list() -> None:
    body = b'{"limit":30,"offset":0,"accounts":[{"id":"a1","name":"Cash","archived":false,"excludeFromStats":false,"balance":{"currencyCode":"USD","currentBalance":12345.67},"initialBalance":null}]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)):
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        accounts = client.get_accounts()
    assert len(accounts) == 1
    assert accounts[0].id == "a1"
    assert accounts[0].name == "Cash"
    assert not accounts[0].archived
    assert not accounts[0].exclude_from_stats
    assert accounts[0].balance is not None
    assert accounts[0].balance.currency_code == "USD"
    assert accounts[0].balance.value == 12345.67


def test_get_categories_parses_list() -> None:
    body = b'{"limit":30,"offset":0,"categories":[{"id":"c1","name":"Food","color":"#FF0000","parentId":null,"archived":false}]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)):
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        categories = client.get_categories()
    assert len(categories) == 1
    assert categories[0].id == "c1"
    assert categories[0].name == "Food"
    assert categories[0].color == "#FF0000"
    assert categories[0].parent_id is None
    assert not categories[0].archived


def test_get_labels_parses_list() -> None:
    body = b'{"limit":30,"offset":0,"labels":[{"id":"l1","name":"Business","color":"#3F51B5","archived":false}]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)):
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        labels = client.get_labels()
    assert len(labels) == 1
    assert labels[0].id == "l1"
    assert labels[0].name == "Business"
    assert labels[0].color == "#3F51B5"
    assert not labels[0].archived


def test_optional_category_and_label_color_are_accepted() -> None:
    category = BudgetBakersWalletClient._parse_category({"id": "c1", "name": "Food"})
    label = BudgetBakersWalletClient._parse_label({"id": "l1", "name": "Business"})
    assert category.color is None
    assert label.color is None


def test_get_record_rules_parses_list() -> None:
    body = b'{"limit":30,"offset":0,"recordRules":[{"id":"r1","name":"Uber rule","keywords":["UBER"],"category":{"id":"cat_03"},"labels":[{"id":"lbl_02"}],"fromAccountId":null,"toAccountId":null}]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)):
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        rules = client.get_record_rules()
    assert len(rules) == 1
    assert rules[0].id == "r1"
    assert rules[0].name == "Uber rule"
    assert rules[0].keywords == ("UBER",)
    assert rules[0].category is not None
    assert rules[0].category.id == "cat_03"
    assert len(rules[0].labels) == 1
    assert rules[0].labels[0].id == "lbl_02"


def test_get_records_parses_list() -> None:
    body = (
        b'{"limit":30,"offset":0,"records":[{"id":"rec_01","accountId":"acct_01","amount":{"value":-42.30,"currencyCode":"USD"},'
        b'"category":{"id":"cat_01"},"counterParty":"MART","recordDate":"2025-07-15",'
        b'"labels":[{"id":"lbl_03"}],"paymentType":"debit_card","recordType":"expense",'
        b'"recordState":"cleared","transfer":null}]}'
    )
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)):
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        records = client.get_records()
    assert len(records) == 1
    assert records[0].id == "rec_01"
    assert records[0].amount.value == -42.30
    assert records[0].amount.currency_code == "USD"


def test_get_records_by_account_sends_query_param() -> None:
    body = b'{"limit":30,"offset":0,"records":[]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)) as open_url:
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        result = client.get_records_by_account(account_id="acct_01")
    request = open_url.call_args.args[0]
    assert result == ()
    assert "accountId=acct_01" in request.full_url


def test_get_records_by_account_url_encodes_query_param() -> None:
    body = b'{"limit":200,"offset":0,"records":[]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)) as open_url:
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        client.get_records_by_account(account_id="acct & 01")
    request = open_url.call_args.args[0]
    assert "accountId=acct+%26+01" in request.full_url


def test_get_accounts_follows_next_offset() -> None:
    first = b'{"limit":200,"offset":0,"nextOffset":200,"accounts":[{"id":"a1","name":"Cash","archived":false,"excludeFromStats":false,"balance":null,"initialBalance":null}]}'
    second = b'{"limit":200,"offset":200,"accounts":[{"id":"a2","name":"Savings","archived":false,"excludeFromStats":false,"balance":null,"initialBalance":null}]}'
    with patch(
        "wallet_v2.adapters.wallet_api.urlopen",
        side_effect=[_mock_urlopen_for_get(first), _mock_urlopen_for_get(second)],
    ) as open_url:
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        accounts = client.get_accounts()
    assert [account.id for account in accounts] == ["a1", "a2"]
    assert "limit=200&offset=0" in open_url.call_args_list[0].args[0].full_url
    assert "limit=200&offset=200" in open_url.call_args_list[1].args[0].full_url


def test_get_accounts_rejects_malformed_envelope() -> None:
    body = b'{"limit":200,"offset":0,"wrongKey":[]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)):
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        with pytest.raises(ValueError, match="accounts"):
            client.get_accounts()


def test_get_accounts_rejects_non_advancing_next_offset() -> None:
    body = b'{"limit":200,"offset":0,"nextOffset":0,"accounts":[]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)):
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        with pytest.raises(ValueError, match="did not advance"):
            client.get_accounts()


def test_get_empty_list_returns_empty() -> None:
    body = b'{"limit":30,"offset":0,"accounts":[]}'
    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_mock_urlopen_for_get(body)):
        client = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        )
        result = client.get_accounts()
    assert result == ()


# ── submit now includes batch result ──────────────────────────────────


def test_submit_parses_batch_result_from_flat_list() -> None:
    class _Response:
        def __enter__(self) -> "_Response":
            return self
        def __exit__(self, *args: object) -> None:
            return None
        def read(self) -> bytes:
            return b'[{"recordId":"r1"},{"recordId":"r2"}]'

    with patch("wallet_v2.adapters.wallet_api.urlopen", return_value=_Response()):
        result = BudgetBakersWalletClient(
            base_url="https://wallet.example.test", api_key="secret", timeout_seconds=2
        ).submit(idempotency_key="idem-1", payload={"amount": 1})

    assert result.batch_result is not None
    assert result.batch_result.all_succeeded
    assert result.batch_result.succeeded_ids == ("r1", "r2")


# ── deserialise: record with transfer ─────────────────────────────────


def test_parse_record_with_transfer() -> None:
    data: dict[str, object] = {
        "id": "rec_04",
        "accountId": "acct_01",
        "amount": {"value": -1000.0, "currencyCode": "USD"},
        "category": {"id": "cat_05"},
        "recordDate": "2025-07-01",
        "transfer": {
            "type": "internal",
            "mirrorRecord": {"id": "rec_mirror_01", "accountId": "acct_02"},
        },
    }
    record = BudgetBakersWalletClient._parse_record(data)
    assert record.record_type is None
    assert record.transfer is not None
    assert record.transfer.type == "internal"
    assert record.transfer.mirror_record is not None
    assert record.transfer.mirror_record.id == "rec_mirror_01"


# ── query-filter helpers ──────────────────────────────────────────────


def test_batch_result_all_succeeded_empty_is_true() -> None:
    result = BatchCreateResult(items=())
    assert result.all_succeeded


def test_batch_result_mixed_is_not_all_succeeded() -> None:
    result = BatchCreateResult(
        items=(
            CreateRecordResponseItem(index=0, status=200, record_id="r1"),
            CreateRecordResponseItem(index=1, status=422),
        )
    )
    assert not result.all_succeeded


def test_create_response_item_is_success() -> None:
    assert CreateRecordResponseItem(index=0, status=200, record_id="r").is_success
    assert not CreateRecordResponseItem(index=0, status=200).is_success
    assert not CreateRecordResponseItem(index=0, status=422).is_success

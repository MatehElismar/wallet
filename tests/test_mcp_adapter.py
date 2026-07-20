"""MCP adapter tests — allowlist, profile gate, JSON-RPC parsing, bounds.

All tests are hermetic: they patch ``urlopen`` and never touch the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.request import Request

import pytest

from wallet_v2.adapters.mcp_client import WalletMcpClient
from wallet_v2.application.contracts_mcp import (
    McpAggregationResult,
    McpBudgetsResult,
    McpClientProfile,
    McpEntityResult,
    McpRecordsResult,
    McpResponseMeta,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "__fixtures__"
    / "mcp_contracts"
    / "v1"
)


def _load_bytes(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


def _make_client() -> WalletMcpClient:
    return WalletMcpClient(
        base_url="https://mcp.example.test",
        api_key="test-key-redacted",
        timeout_seconds=5,
    )


class _Response:
    """Minimal mock HTTP response for urlopen patching."""

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self._headers = headers or {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    @property
    def headers(self) -> dict[str, str]:
        return self._headers


def _responding(*body_list: bytes, headers: dict[str, str] | None = None) -> Any:
    """Return a urlopen side_effect that echoes request ids into responses.

    Accepts one or more response body bytes and cycles through them on
    successive calls to urlopen.  Each response's ``id`` is patched to match
    the request so that JSON-RPC id validation passes.
    """
    responses = [json.loads(b) for b in body_list]
    it = iter(responses)

    def side_effect(req: Request, **kwargs: Any) -> _Response:
        try:
            resp_data = next(it)
        except StopIteration:
            raise AssertionError("more urlopen calls than prepared responses")
        resp_data["id"] = json.loads(req.data)["id"]
        return _Response(json.dumps(resp_data).encode("utf-8"), headers=headers)

    return side_effect


# ── Write tools are unreachable even with hypothetical write scopes ─────


class TestWriteToolsBlockedRegardlessOfScopes:
    """Defense in depth: the allowlist rejects write tool names before any
    network I/O, so granting write scopes to a credential cannot enable a
    write operation through this adapter."""

    WRITE_TOOL_NAMES = [
        "create_record",
        "update_record",
        "patch_record",
        "delete_record",
        "post_record",
        "put_record",
        "upsert_record",
        "submit_record",
        "create_transaction",
        "update_transaction",
        "delete_transaction",
    ]

    def _client_with_write_scopes(self) -> WalletMcpClient:
        client = _make_client()
        # Simulate a credential that was granted every plausible write scope.
        client._profile_validated = True
        client._observed_scopes = (
            "accounts.read",
            "records.read",
            "records.write",
            "transactions.write",
            "budgets.read",
            "budgets.write",
            "record_rules.read",
            "record_rules.write",
        )
        return client

    @pytest.mark.parametrize("tool_name", WRITE_TOOL_NAMES)
    def test_write_tool_rejected_before_network(self, tool_name: str) -> None:
        client = self._client_with_write_scopes()
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="disallowed MCP tool"):
                client._call(tool_name, {"amount": 100})
            mock.assert_not_called()

    def test_wildcard_write_scope_does_not_enable_write_tools(self) -> None:
        client = _make_client()
        client._profile_validated = True
        client._observed_scopes = ("*",)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="disallowed MCP tool"):
                client._call("create_record", {"amount": 1})
            mock.assert_not_called()

    def test_no_public_write_method_on_client(self) -> None:
        client = self._client_with_write_scopes()
        for tool_name in self.WRITE_TOOL_NAMES:
            assert not hasattr(client, tool_name), (
                f"adapter must not expose a write method {tool_name!r}"
            )


# ── Endpoint and envelope contract ─────────────────────────────────────


class TestWireContract:
    def test_posts_to_base_url_not_v1_mcp(self) -> None:
        body = _load_bytes("get_client_profile.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ) as mock:
            client = _make_client()
            client.get_client_profile()
            call_args = mock.call_args
            req = call_args[0][0] if call_args and call_args[0] else None
            assert req is not None
            assert req.full_url == "https://mcp.example.test"

    def test_jsonrpc_method_is_tools_call(self) -> None:
        body = _load_bytes("get_client_profile.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ) as mock:
            client = _make_client()
            client.get_client_profile()
            req = mock.call_args[0][0]
            sent = json.loads(req.data)
            assert sent["method"] == "tools/call"
            assert sent["params"]["name"] == "get_client_profile"
            assert isinstance(sent["params"]["arguments"], dict)

    def test_headers_include_accept_and_mcp_protocol_version(self) -> None:
        body = _load_bytes("get_client_profile.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ) as mock:
            client = _make_client()
            client.get_client_profile()
            req = mock.call_args[0][0]
            assert req.headers["Content-type"] == "application/json"
            assert req.headers["Accept"] == "application/json, text/event-stream"
            assert req.headers["Mcp-protocol-version"] == "2025-03-26"
            assert req.headers["Authorization"] == "Bearer test-key-redacted"

    def test_structured_content_parsed_from_result(self) -> None:
        body = _load_bytes("get_records.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("records.read",)
            result = client.get_records(account_id="acct_mcp_01")
            assert len(result.records) == 2

    def test_records_sends_record_date_as_prefix_array(self) -> None:
        body = _load_bytes("get_records.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ) as mock:
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("records.read",)
            client.get_records(
                account_id="acct_01", date_from="2026-01-01", date_to="2026-02-01",
            )
            req = mock.call_args[0][0]
            sent = json.loads(req.data)
            args = sent["params"]["arguments"]
            assert args["accountId"] == "acct_01"
            assert args["recordDate"] == ["gte.2026-01-01", "lt.2026-02-01"]

    def test_aggregation_groupBy_is_array(self) -> None:
        body = _load_bytes("get_records_aggregation.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ) as mock:
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("records.read",)
            client.get_records_aggregation(account_id="acct_01", group_by="category")
            req = mock.call_args[0][0]
            sent = json.loads(req.data)
            args = sent["params"]["arguments"]
            assert args["groupBy"] == ["category"]

    def test_entity_sends_documentType_not_kind_id(self) -> None:
        body = _load_bytes("get_entity_record_rule.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ) as mock:
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("record_rules.read",)
            client.get_entity(document_type="record_rules")
            req = mock.call_args[0][0]
            sent = json.loads(req.data)
            args = sent["params"]["arguments"]
            assert args["documentType"] == "record-rules"
            assert "kind" not in args
            assert "id" not in args


# ── Allowlist fail-closed ─────────────────────────────────────────────


class TestAllowlist:
    def test_disallowed_tool_raises_before_network(self) -> None:
        client = _make_client()
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="disallowed MCP tool"):
                client._call("create_record", {"amount": 100})
            mock.assert_not_called()

    def test_unknown_tool_raises(self) -> None:
        client = _make_client()
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="disallowed MCP tool"):
                client._call("delete_record", {"id": "x"})
            mock.assert_not_called()

    def test_all_allowed_tools_are_accepted_by_call(self) -> None:
        client = _make_client()
        allowed = client.ALLOWED_TOOLS
        assert "get_client_profile" in allowed
        assert "get_records" in allowed
        assert "get_records_aggregation" in allowed
        assert "get_budgets" in allowed
        assert "get_entity" in allowed
        assert "create_record" not in allowed
        assert "update_record" not in allowed
        assert "delete_record" not in allowed

    def test_entity_rejects_non_record_rules_document_type(self) -> None:
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("record_rules.read",)
            with pytest.raises(ValueError, match="disallowed entity document_type"):
                client.get_entity(document_type="accounts")
            mock.assert_not_called()

    def test_get_entity_document_type_is_literal_record_rules(self) -> None:
        from typing import Literal, get_args, get_origin, get_type_hints

        hints = get_type_hints(WalletMcpClient.get_entity)
        dt = hints["document_type"]
        assert get_origin(dt) is Literal
        assert get_args(dt) == ("record_rules",)


# ── Profile gate ──────────────────────────────────────────────────────


class TestProfileGate:
    def test_get_client_profile_must_be_called_first(self) -> None:
        client = _make_client()
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(RuntimeError, match="profile not validated"):
                client.get_records(account_id="acct_01")
            mock.assert_not_called()

    def test_requires_complete_sync_state(self) -> None:
        bad_body = _load_bytes("get_client_profile_bad_sync.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(bad_body),
        ):
            client = _make_client()
            with pytest.raises(ValueError, match="syncState.*incomplete"):
                client.get_client_profile()
        assert not client._profile_validated

    def test_valid_profile_gate_passes(self) -> None:
        body = _load_bytes("get_client_profile.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            profile = client.get_client_profile()
        assert client._profile_validated is True
        assert profile.sync_state == "complete"
        assert "records.read" in profile.granted_scopes

    def test_missing_scope_blocks_operation(self) -> None:
        profile_body = json.dumps({
            "jsonrpc": "2.0",
            "id": "test",
            "result": {
                "structuredContent": {
                    "syncState": "complete",
                    "grantedScopes": ["accounts.read"],
                },
            },
        }).encode("utf-8")

        records_body = _load_bytes("get_records.json")

        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(profile_body, records_body),
        ):
            client = _make_client()
            profile = client.get_client_profile()
            assert profile.sync_state == "complete"
            assert "records.read" not in profile.granted_scopes
            with pytest.raises(PermissionError, match="records.read"):
                client.get_records(account_id="acct_01")


# ── get_client_profile ────────────────────────────────────────────────


class TestGetClientProfile:
    def test_parses_full_profile(self) -> None:
        body = _load_bytes("get_client_profile.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            profile = client.get_client_profile()

        assert isinstance(profile, McpClientProfile)
        assert profile.sync_state == "complete"
        assert len(profile.granted_scopes) >= 5
        assert profile.synced_at is not None
        assert profile.raw_profile is not None

    def test_tracks_response_meta_from_structured_content(self) -> None:
        body = _load_bytes("get_client_profile.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            client.get_client_profile()

        meta = client.last_response_meta
        assert meta.synced_at == "2026-07-19T10:00:00Z"
        assert meta.rate_limit_capacity == 300
        assert meta.rate_limit_remaining == 300
        assert meta.rate_limit_refill_per_minute == 60


# ── get_records ───────────────────────────────────────────────────────


class TestGetRecords:
    @staticmethod
    def _with_profile(client: WalletMcpClient) -> None:
        client._profile_validated = True
        client._observed_scopes = ("records.read",)

    def test_parses_records(self) -> None:
        body = _load_bytes("get_records.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            self._with_profile(client)
            result = client.get_records(account_id="acct_mcp_01")

        assert isinstance(result, McpRecordsResult)
        assert len(result.records) == 2
        assert result.total == 2
        assert result.offset == 0
        assert result.limit == 200
        assert result.next_offset == 2

        first = result.records[0]
        assert first.id == "rec_mcp_01"
        assert first.amount_value == -42.30
        assert first.currency == "USD"
        assert first.counter_party == "Online Store"
        assert first.category is not None
        assert first.category.id == "cat_mcp_01"
        assert first.category.name == "Groceries"
        assert len(first.labels) == 2
        assert first.labels[0].id == "lbl_mcp_01"
        assert first.labels[0].name == "Food"
        assert first.payment_type == "debit_card"
        assert first.source == "manual"
        assert first.account_is_bank_sync is False

    def test_empty_records(self) -> None:
        body = _load_bytes("get_records_empty.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            self._with_profile(client)
            result = client.get_records(account_id="acct_mcp_01")

        assert len(result.records) == 0
        assert result.total == 0
        assert result.next_offset is None

    def test_rejects_invalid_bounds(self) -> None:
        client = _make_client()
        self._with_profile(client)
        with pytest.raises(ValueError, match="limit must be >= 1"):
            client.get_records(account_id="x", limit=0)
        with pytest.raises(ValueError, match="limit must be <= 500"):
            client.get_records(account_id="x", limit=501)
        with pytest.raises(ValueError, match="offset must be >= 0"):
            client.get_records(account_id="x", offset=-1)

    def test_rejects_empty_account_id(self) -> None:
        client = _make_client()
        self._with_profile(client)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="account_id must not be empty"):
                client.get_records(account_id="")
            mock.assert_not_called()

    def test_rejects_non_iso_date_from(self) -> None:
        client = _make_client()
        self._with_profile(client)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="date_from.*not a valid ISO"):
                client.get_records(account_id="acct_01", date_from="2026/01/01")
            mock.assert_not_called()

    def test_rejects_non_iso_date_to(self) -> None:
        client = _make_client()
        self._with_profile(client)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="date_to.*not a valid ISO"):
                client.get_records(account_id="acct_01", date_to="not-a-date")
            mock.assert_not_called()

    def test_rejects_inverted_date_range(self) -> None:
        client = _make_client()
        self._with_profile(client)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="date_from.*must not be later"):
                client.get_records(
                    account_id="acct_01",
                    date_from="2026-03-01",
                    date_to="2026-01-01",
                )
            mock.assert_not_called()

    def test_accepts_valid_iso_date_range(self) -> None:
        body = _load_bytes("get_records.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            self._with_profile(client)
            result = client.get_records(
                account_id="acct_01",
                date_from="2026-01-01",
                date_to="2026-01-02",
            )
        assert isinstance(result, McpRecordsResult)

    def test_accepts_equal_date_from_and_date_to(self) -> None:
        body = _load_bytes("get_records.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            self._with_profile(client)
            result = client.get_records(
                account_id="acct_01",
                date_from="2026-01-01",
                date_to="2026-01-01",
            )
        assert isinstance(result, McpRecordsResult)


# ── get_records_aggregation ───────────────────────────────────────────


class TestGetRecordsAggregation:
    def test_parses_aggregation(self) -> None:
        body = _load_bytes("get_records_aggregation.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("records.read",)
            result = client.get_records_aggregation(
                account_id="acct_mcp_01", group_by="category"
            )

        assert isinstance(result, McpAggregationResult)
        assert len(result.results) == 3
        assert result.results[0].key == "cat_mcp_01"
        assert result.results[0].value == -42.30
        assert result.results[0].count == 1
        assert result.offset == 0
        assert result.limit == 200
        assert result.base_currency == "USD"
        assert result.transfers_included is False

    def test_rejects_invalid_bounds(self) -> None:
        client = _make_client()
        client._profile_validated = True
        client._observed_scopes = ("records.read",)
        with pytest.raises(ValueError, match="limit must be >= 1"):
            client.get_records_aggregation(
                account_id="x", group_by="category", limit=0
            )
        with pytest.raises(ValueError, match="limit must be <= 500"):
            client.get_records_aggregation(
                account_id="x", group_by="category", limit=501
            )
        with pytest.raises(ValueError, match="offset must be >= 0"):
            client.get_records_aggregation(
                account_id="x", group_by="category", offset=-1
            )

    def test_rejects_empty_account_id(self) -> None:
        client = _make_client()
        client._profile_validated = True
        client._observed_scopes = ("records.read",)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="account_id must not be empty"):
                client.get_records_aggregation(
                    account_id="", group_by="category"
                )
            mock.assert_not_called()

    def test_rejects_non_iso_date_from(self) -> None:
        client = _make_client()
        client._profile_validated = True
        client._observed_scopes = ("records.read",)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="date_from.*not a valid ISO"):
                client.get_records_aggregation(
                    account_id="acct_01",
                    group_by="category",
                    date_from="01-01-2026",
                )
            mock.assert_not_called()

    def test_rejects_non_iso_date_to(self) -> None:
        client = _make_client()
        client._profile_validated = True
        client._observed_scopes = ("records.read",)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="date_to.*not a valid ISO"):
                client.get_records_aggregation(
                    account_id="acct_01",
                    group_by="category",
                    date_to="2026-13-40",
                )
            mock.assert_not_called()

    def test_rejects_inverted_date_range(self) -> None:
        client = _make_client()
        client._profile_validated = True
        client._observed_scopes = ("records.read",)
        with patch("wallet_v2.adapters.mcp_client.urlopen") as mock:
            with pytest.raises(ValueError, match="date_from.*must not be later"):
                client.get_records_aggregation(
                    account_id="acct_01",
                    group_by="category",
                    date_from="2026-02-01",
                    date_to="2026-01-01",
                )
            mock.assert_not_called()

    def test_accepts_valid_iso_date_range(self) -> None:
        body = _load_bytes("get_records_aggregation.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("records.read",)
            result = client.get_records_aggregation(
                account_id="acct_01",
                group_by="category",
                date_from="2026-01-01",
                date_to="2026-01-31",
            )
        assert isinstance(result, McpAggregationResult)


# ── get_budgets ───────────────────────────────────────────────────────


class TestGetBudgets:
    def test_parses_budgets(self) -> None:
        body = _load_bytes("get_budgets.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("budgets.read",)
            result = client.get_budgets(account_id="acct_mcp_01")

        assert isinstance(result, McpBudgetsResult)
        assert len(result.budgets) == 2
        assert result.total == 2
        assert result.limit == 200
        assert result.offset == 0
        assert result.budgets[0].id == "bgt_mcp_01"
        assert result.budgets[0].name == "Groceries"
        assert result.budgets[0].amount == 500.00
        assert result.budgets[0].spent == 320.50
        assert result.budgets[0].remaining == 179.50

    def test_rejects_empty_account_id(self) -> None:
        client = _make_client()
        client._profile_validated = True
        client._observed_scopes = ("budgets.read",)
        with pytest.raises(ValueError, match="account_id must not be empty"):
            client.get_budgets(account_id="")

    def test_hard_cap_enforced(self) -> None:
        many_budgets = [
            {"id": f"b{i}", "name": "x", "period": "m", "amount": 1.0}
            for i in range(1001)
        ]
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": "test",
            "result": {
                "structuredContent": {"budgets": many_budgets},
            },
        }).encode("utf-8")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("budgets.read",)
            with pytest.raises(ValueError, match="exceeds hard cap"):
                client.get_budgets(account_id="acct_mcp_01")


# ── get_entity ────────────────────────────────────────────────────────


class TestGetEntity:
    def test_parses_record_rule_entity(self) -> None:
        body = _load_bytes("get_entity_record_rule.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            client._profile_validated = True
            client._observed_scopes = ("record_rules.read",)
            result = client.get_entity(document_type="record_rules")

        assert isinstance(result, McpEntityResult)
        assert result.document_type == "record-rules"
        assert len(result.results) == 1
        assert result.results[0].get("id") == "rule_mcp_01"
        assert "keywords" in result.results[0]


# ── JSON-RPC error handling ───────────────────────────────────────────


class TestJsonRpcError:
    def test_error_response_raises_value_error(self) -> None:
        body = _load_bytes("mcp_error_response.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            with pytest.raises(ValueError, match="MCP error"):
                client._call("get_client_profile")

    def test_non_jsonrpc_response_raises(self) -> None:
        body = b'{"result": {"structuredContent": {"ok": true}}}'
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            with pytest.raises(ValueError, match="JSON-RPC 2.0"):
                client._call("get_client_profile")

    def test_missing_result_raises(self) -> None:
        body = b'{"jsonrpc": "2.0", "id": "1"}'
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            with pytest.raises(ValueError, match="result"):
                client._call("get_client_profile")

    def test_missing_structured_content_raises(self) -> None:
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": "test",
            "result": {"notStructured": True},
        }).encode("utf-8")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            with pytest.raises(ValueError, match="structuredContent"):
                client._call("get_client_profile")


class TestJsonDecodeError:
    def test_non_json_response_raises_value_error(self) -> None:
        body = b"not-json-at-all"
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            return_value=_Response(body),
        ):
            client = _make_client()
            with pytest.raises(ValueError, match="not valid JSON"):
                client._call("get_client_profile")

    def test_empty_body_raises_value_error(self) -> None:
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            return_value=_Response(b""),
        ):
            client = _make_client()
            with pytest.raises(ValueError, match="not valid JSON"):
                client._call("get_client_profile")

    def test_json_decode_error_is_value_error_subclass(self) -> None:
        import json as _json

        assert issubclass(_json.JSONDecodeError, ValueError)


class TestUrlErrorTimeout:
    def test_url_error_with_timeout_reason_raises_timeout_error(self) -> None:
        import socket
        from urllib.error import URLError

        def side_effect(req: Request, **kwargs: Any) -> Any:
            raise URLError(socket.timeout("timed out"))

        client = _make_client()
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen", side_effect=side_effect
        ):
            with pytest.raises(TimeoutError, match="MCP request timed out"):
                client._call("get_client_profile")

    def test_url_error_with_non_timeout_reason_raises_connection_error(
        self,
    ) -> None:
        from urllib.error import URLError

        def side_effect(req: Request, **kwargs: Any) -> Any:
            raise URLError("connection refused")

        client = _make_client()
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen", side_effect=side_effect
        ):
            with pytest.raises(ConnectionError, match="connection failed"):
                client._call("get_client_profile")

    def test_direct_timeout_error_propagates_as_timeout_error(self) -> None:
        def side_effect(req: Request, **kwargs: Any) -> Any:
            raise TimeoutError("socket timed out")

        client = _make_client()
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen", side_effect=side_effect
        ):
            with pytest.raises(TimeoutError, match="MCP request timed out"):
                client._call("get_client_profile")


class TestJsonRpcIdMismatch:
    def test_mismatched_response_id_raises(self) -> None:
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": "wrong-id",
            "result": {
                "structuredContent": {"syncState": "complete"},
            },
        }).encode("utf-8")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            return_value=_Response(body),
        ):
            client = _make_client()
            with pytest.raises(ValueError, match="does not match"):
                client._call("get_client_profile")


# ── Static parsing (no network) ───────────────────────────────────────


class TestStaticParsing:
    def test_parse_record_minimal(self) -> None:
        data: dict[str, object] = {
            "id": "rec_test",
            "accountId": "acct_test",
            "amount": {"value": -10.0, "currencyCode": "USD"},
            "recordDate": "2026-07-01",
        }
        record = WalletMcpClient._parse_record(data)
        assert record.id == "rec_test"
        assert record.amount_value == -10.0
        assert record.currency == "USD"
        assert record.counter_party is None
        assert record.category is None
        assert record.labels == ()

    def test_parse_record_with_all_fields(self) -> None:
        data: dict[str, object] = {
            "id": "rec_full",
            "accountId": "acct_full",
            "amount": {"value": -99.99, "currencyCode": "EUR"},
            "recordDate": "2026-07-15",
            "counterParty": "Test Merchant",
            "category": {"id": "cat_full", "name": "Test Category"},
            "labels": [
                {"id": "lbl_a", "name": "Label A"},
                {"id": "lbl_b", "name": "Label B"},
            ],
            "paymentType": "credit_card",
            "recordState": "pending",
            "source": "bank_sync",
            "accountIsBankSync": True,
        }
        record = WalletMcpClient._parse_record(data)
        assert record.counter_party == "Test Merchant"
        assert record.category is not None
        assert record.category.id == "cat_full"
        assert record.category.name == "Test Category"
        assert len(record.labels) == 2
        assert record.labels[0].id == "lbl_a"
        assert record.labels[0].name == "Label A"
        assert record.payment_type == "credit_card"
        assert record.record_state == "pending"
        assert record.source == "bank_sync"
        assert record.account_is_bank_sync is True


class TestParseRecordFailClosed:
    def test_missing_amount_raises(self) -> None:
        data: dict[str, object] = {
            "id": "rec_test",
            "accountId": "acct_test",
            "recordDate": "2026-07-01",
        }
        with pytest.raises(ValueError, match="missing or invalid 'amount'"):
            WalletMcpClient._parse_record(data)

    def test_non_dict_amount_raises(self) -> None:
        data: dict[str, object] = {
            "id": "rec_test",
            "accountId": "acct_test",
            "amount": "not-a-dict",
            "recordDate": "2026-07-01",
        }
        with pytest.raises(ValueError, match="missing or invalid 'amount'"):
            WalletMcpClient._parse_record(data)

    def test_missing_value_raises(self) -> None:
        data: dict[str, object] = {
            "id": "rec_test",
            "accountId": "acct_test",
            "amount": {"currencyCode": "USD"},
            "recordDate": "2026-07-01",
        }
        with pytest.raises(ValueError, match="amount.value"):
            WalletMcpClient._parse_record(data)

    def test_non_numeric_value_raises(self) -> None:
        data: dict[str, object] = {
            "id": "rec_test",
            "accountId": "acct_test",
            "amount": {"value": "not-a-number", "currencyCode": "USD"},
            "recordDate": "2026-07-01",
        }
        with pytest.raises(ValueError, match="amount.value"):
            WalletMcpClient._parse_record(data)

    def test_missing_currency_raises(self) -> None:
        data: dict[str, object] = {
            "id": "rec_test",
            "accountId": "acct_test",
            "amount": {"value": -10.0},
            "recordDate": "2026-07-01",
        }
        with pytest.raises(ValueError, match="amount.currencyCode"):
            WalletMcpClient._parse_record(data)

    def test_empty_currency_raises(self) -> None:
        data: dict[str, object] = {
            "id": "rec_test",
            "accountId": "acct_test",
            "amount": {"value": -10.0, "currencyCode": ""},
            "recordDate": "2026-07-01",
        }
        with pytest.raises(ValueError, match="amount.currencyCode"):
            WalletMcpClient._parse_record(data)


# ── ProfileValidated property ─────────────────────────────────────────


class TestProfileValidatedProperty:
    def test_starts_false(self) -> None:
        client = _make_client()
        assert client.profile_validated is False

    def test_becomes_true_after_valid_profile(self) -> None:
        body = _load_bytes("get_client_profile.json")
        with patch(
            "wallet_v2.adapters.mcp_client.urlopen",
            side_effect=_responding(body),
        ):
            client = _make_client()
            client.get_client_profile()
        assert client.profile_validated is True

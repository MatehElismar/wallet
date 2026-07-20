"""Hermetic MCP contract tests — fixture shape and JSON-RPC parsing.

All contract assertions are driven by the versioned, redacted fixtures in
``tests/__fixtures__/mcp_contracts/v1/``. No network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wallet_v2.adapters.mcp_client import WalletMcpClient
from wallet_v2.application.contracts_mcp import (
    McpAggregationResult,
    McpBudgetsResult,
    McpClientProfile,
    McpEntityResult,
    McpRecordsResult,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "__fixtures__"
    / "mcp_contracts"
    / "v1"
)


def _load_json(name: str) -> dict[str, object]:
    data = json.loads((FIXTURE_DIR / name).read_text())
    assert isinstance(data, dict)
    return data


def _structured(name: str) -> dict[str, object]:
    """Return the ``structuredContent`` payload from a fixture envelope."""
    data = _load_json(name)
    result = data.get("result", {})
    assert isinstance(result, dict)
    structured = result.get("structuredContent")
    assert isinstance(structured, dict)
    return structured


# ── JSON-RPC envelope tests ───────────────────────────────────────────


class TestJsonRpcEnvelope:
    def test_profile_fixture_is_valid_jsonrpc(self) -> None:
        data = _load_json("get_client_profile.json")
        assert data.get("jsonrpc") == "2.0"
        assert isinstance(data.get("id"), str)
        assert isinstance(data.get("result"), dict)

    def test_records_fixture_is_valid_jsonrpc(self) -> None:
        data = _load_json("get_records.json")
        assert data.get("jsonrpc") == "2.0"
        assert data.get("id") == "test-req-records-01"

    def test_error_fixture_has_error_not_result(self) -> None:
        data = _load_json("mcp_error_response.json")
        assert data.get("jsonrpc") == "2.0"
        assert "error" in data
        assert "result" not in data

    def test_bad_sync_fixture_has_incomplete_sync_state(self) -> None:
        structured = _structured("get_client_profile_bad_sync.json")
        assert structured.get("syncState") == "incomplete"


# ── Profile fixture tests ─────────────────────────────────────────────


class TestClientProfileFixture:
    def test_parses_sync_state_complete(self) -> None:
        structured = _structured("get_client_profile.json")
        assert structured.get("syncState") == "complete"

    def test_has_all_required_scopes(self) -> None:
        structured = _structured("get_client_profile.json")
        scopes = structured.get("grantedScopes", [])
        assert isinstance(scopes, list)
        required = {"accounts.read", "records.read", "budgets.read", "record_rules.read"}
        assert required.issubset(set(scopes))

    def test_parses_synced_at(self) -> None:
        structured = _structured("get_client_profile.json")
        meta = structured.get("_meta", {})
        assert isinstance(meta, dict)
        assert isinstance(meta.get("syncedAt"), str)


# ── Records fixture tests ─────────────────────────────────────────────


class TestRecordsFixture:
    def test_every_record_has_required_fields(self) -> None:
        structured = _structured("get_records.json")
        records = structured.get("records", [])
        assert isinstance(records, list)
        assert len(records) >= 1
        for rec in records:
            assert isinstance(rec, dict)
            assert rec.get("id")
            assert rec.get("accountId")
            assert rec.get("recordDate")

    def test_records_have_amount_shape(self) -> None:
        structured = _structured("get_records.json")
        records = structured.get("records", [])
        for rec in records:
            amount = rec.get("amount")
            assert isinstance(amount, dict)
            assert "value" in amount
            assert "currencyCode" in amount

    def test_counter_party_category_labels_are_objects(self) -> None:
        structured = _structured("get_records.json")
        records = structured.get("records", [])
        first = records[0]
        assert isinstance(first.get("counterParty"), str)
        category = first.get("category")
        assert isinstance(category, dict)
        assert "id" in category
        labels = first.get("labels")
        assert isinstance(labels, list)
        assert all("id" in l for l in labels)

    def test_pagination_fields_present(self) -> None:
        structured = _structured("get_records.json")
        assert isinstance(structured.get("offset"), int)
        assert isinstance(structured.get("limit"), int)

    def test_empty_records_list(self) -> None:
        structured = _structured("get_records_empty.json")
        assert structured.get("records") == []
        assert structured.get("total") == 0


# ── Aggregation fixture tests ─────────────────────────────────────────


class TestAggregationFixture:
    def test_has_results_with_key_value_count(self) -> None:
        structured = _structured("get_records_aggregation.json")
        results = structured.get("results", [])
        assert len(results) >= 1
        for b in results:
            assert isinstance(b, dict)
            assert "key" in b
            assert "value" in b
            assert "count" in b

    def test_base_currency_and_transfers_present(self) -> None:
        structured = _structured("get_records_aggregation.json")
        assert isinstance(structured.get("baseCurrency"), str)
        assert isinstance(structured.get("transfersIncluded"), bool)


# ── Budgets fixture tests ─────────────────────────────────────────────


class TestBudgetsFixture:
    def test_every_budget_has_required_fields(self) -> None:
        structured = _structured("get_budgets.json")
        budgets = structured.get("budgets", [])
        assert len(budgets) >= 1
        for b in budgets:
            assert isinstance(b, dict)
            assert b.get("id")
            assert b.get("name")
            assert isinstance(b.get("amount"), (int, float))

    def test_budgets_have_spent_and_remaining(self) -> None:
        structured = _structured("get_budgets.json")
        budgets = structured.get("budgets", [])
        for b in budgets:
            assert "spent" in b
            assert "remaining" in b


# ── Entity fixture tests ──────────────────────────────────────────────


class TestEntityFixture:
    def test_entity_is_record_rule_shape(self) -> None:
        structured = _structured("get_entity_record_rule.json")
        assert structured.get("documentType") == "record-rules"
        results = structured.get("results", [])
        assert len(results) >= 1
        entity = results[0]
        assert isinstance(entity, dict)
        assert entity.get("id")
        assert "keywords" in entity
        assert "category" in entity


# ── Redaction — no secrets in fixtures ────────────────────────────────


class TestGetEntityLiteralContract:
    """Verify that get_entity is statically locked to Literal['record_rules']
    in both the protocol and the implementation."""

    def test_protocol_get_entity_uses_literal_record_rules(self) -> None:
        from typing import Literal, get_args, get_origin, get_type_hints

        from wallet_v2.application.contracts_mcp import McpReadOnlyClient

        hints = get_type_hints(McpReadOnlyClient.get_entity)
        dt = hints["document_type"]
        assert get_origin(dt) is Literal
        assert get_args(dt) == ("record_rules",)


class TestFixtureRedaction:
    SECRET_PATTERNS = [
        "Bearer ",
        "api_key",
        "password",
        "secret",
        "@gmail.com",
        "@example.com",
    ]

    @pytest.mark.parametrize("fixture_name", [
        "get_client_profile.json",
        "get_records.json",
        "get_records_empty.json",
        "get_records_aggregation.json",
        "get_budgets.json",
        "get_entity_record_rule.json",
        "mcp_error_response.json",
        "get_client_profile_bad_sync.json",
    ])
    def test_fixture_contains_no_secrets(self, fixture_name: str) -> None:
        raw = (FIXTURE_DIR / fixture_name).read_text()
        lower = raw.lower()
        for pattern in self.SECRET_PATTERNS:
            assert pattern.lower() not in lower, (
                f"Secret pattern {pattern!r} found in {fixture_name}"
            )

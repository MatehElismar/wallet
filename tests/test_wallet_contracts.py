"""Hermetic Wallet REST contract tests — fixture shape and batch result parsing.

All contract assertions are driven by the versioned, redacted fixtures in
``tests/__fixtures__/wallet_contracts/v1/``. No network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wallet_v2.adapters.wallet_api import BudgetBakersWalletClient
from wallet_v2.application.contracts import (
    CreateRecordRequest,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "__fixtures__" / "wallet_contracts" / "v1"


def _load_json(name: str) -> object:
    return json.loads((FIXTURE_DIR / name).read_text())


# ── fixture shape tests ───────────────────────────────────────────────


class TestAccountsFixture:
    @staticmethod
    def _load_accounts():
        data = _load_json("accounts.json")
        assert isinstance(data, dict)
        items = data.get("accounts", [])
        assert isinstance(items, list)
        return items

    def test_every_account_has_required_fields(self) -> None:
        for item in self._load_accounts():
            account = BudgetBakersWalletClient._parse_account(item)
            assert account.id
            assert account.name

    def test_parses_balance(self) -> None:
        accounts = [
            BudgetBakersWalletClient._parse_account(item)
            for item in self._load_accounts()
        ]
        with_balance = [a for a in accounts if a.balance is not None]
        assert len(with_balance) > 0
        for a in with_balance:
            assert a.balance.currency_code
            assert isinstance(a.balance.value, float)

    def test_parses_archived_flag(self) -> None:
        archived = [
            BudgetBakersWalletClient._parse_account(item)
            for item in self._load_accounts()
        ]
        assert any(a.archived for a in archived)
        assert any(not a.archived for a in archived)

    def test_parses_exclude_from_stats(self) -> None:
        accounts = [
            BudgetBakersWalletClient._parse_account(item)
            for item in self._load_accounts()
        ]
        assert any(a.exclude_from_stats for a in accounts)
        assert any(not a.exclude_from_stats for a in accounts)

    def test_parses_initial_balance(self) -> None:
        accounts = [
            BudgetBakersWalletClient._parse_account(item)
            for item in self._load_accounts()
        ]
        with_initial = [a for a in accounts if a.initial_balance is not None]
        assert len(with_initial) > 0
        for a in with_initial:
            assert a.initial_balance.currency_code
            assert isinstance(a.initial_balance.value, float)


class TestCategoriesFixture:
    @staticmethod
    def _load_categories():
        data = _load_json("categories.json")
        assert isinstance(data, dict)
        items = data.get("categories", [])
        assert isinstance(items, list)
        return items

    def test_every_category_has_required_fields(self) -> None:
        for item in self._load_categories():
            cat = BudgetBakersWalletClient._parse_category(item)
            assert cat.id
            assert cat.name
            assert cat.color

    def test_parses_parent_child_relationship(self) -> None:
        categories = [
            BudgetBakersWalletClient._parse_category(item)
            for item in self._load_categories()
        ]
        parent_ids = {c.id for c in categories}
        sub_ids = {c.parent_id for c in categories if c.parent_id}
        assert sub_ids <= parent_ids

    def test_parses_archived_flag(self) -> None:
        categories = [
            BudgetBakersWalletClient._parse_category(item)
            for item in self._load_categories()
        ]
        assert any(c.archived for c in categories)


class TestLabelsFixture:
    @staticmethod
    def _load_labels():
        data = _load_json("labels.json")
        assert isinstance(data, dict)
        items = data.get("labels", [])
        assert isinstance(items, list)
        return items

    def test_every_label_has_required_fields(self) -> None:
        for item in self._load_labels():
            label = BudgetBakersWalletClient._parse_label(item)
            assert label.id
            assert label.name
            assert label.color
            assert not label.archived

    def test_parses_archived_flag(self) -> None:
        labels = [
            BudgetBakersWalletClient._parse_label(item)
            for item in self._load_labels()
        ]
        assert all(not l.archived for l in labels)


class TestRecordRulesFixture:
    @staticmethod
    def _load_rules():
        data = _load_json("record_rules.json")
        assert isinstance(data, dict)
        items = data.get("recordRules", [])
        assert isinstance(items, list)
        return items

    def test_every_rule_has_required_fields(self) -> None:
        for item in self._load_rules():
            rule = BudgetBakersWalletClient._parse_record_rule(item)
            assert rule.id

    def test_parses_keywords(self) -> None:
        rules = [
            BudgetBakersWalletClient._parse_record_rule(item)
            for item in self._load_rules()
        ]
        with_kw = [r for r in rules if r.keywords]
        assert len(with_kw) > 0
        for r in with_kw:
            assert all(isinstance(k, str) for k in r.keywords)

    def test_parses_category_ref(self) -> None:
        rules = [
            BudgetBakersWalletClient._parse_record_rule(item)
            for item in self._load_rules()
        ]
        with_cat = [r for r in rules if r.category is not None]
        assert len(with_cat) > 0
        for r in with_cat:
            assert r.category.id

    def test_parses_labels_refs(self) -> None:
        rules = [
            BudgetBakersWalletClient._parse_record_rule(item)
            for item in self._load_rules()
        ]
        with_labels = [r for r in rules if r.labels]
        assert len(with_labels) > 0
        for r in with_labels:
            assert all(lbl.id for lbl in r.labels)

    def test_parses_to_account(self) -> None:
        rules = [
            BudgetBakersWalletClient._parse_record_rule(item)
            for item in self._load_rules()
        ]
        with_to = [r for r in rules if r.to_account_id is not None]
        assert len(with_to) > 0


class TestRecordsFixture:
    @staticmethod
    def _load_records():
        data = _load_json("records.json")
        assert isinstance(data, dict)
        items = data.get("records", [])
        assert isinstance(items, list)
        return items

    def test_every_record_has_required_fields(self) -> None:
        for item in self._load_records():
            record = BudgetBakersWalletClient._parse_record(item)
            assert record.id
            assert record.account_id
            assert record.record_date
            assert record.amount.value != 0

    def test_parses_category_ref(self) -> None:
        records = [
            BudgetBakersWalletClient._parse_record(item)
            for item in self._load_records()
        ]
        with_cat = [r for r in records if r.category is not None]
        assert len(with_cat) > 0
        for r in with_cat:
            assert r.category.id

    def test_negative_amount_is_expense(self) -> None:
        records = [
            BudgetBakersWalletClient._parse_record(item)
            for item in self._load_records()
        ]
        expenses_or_transfer = [r for r in records if r.amount.value < 0]
        assert len(expenses_or_transfer) > 0
        for r in expenses_or_transfer:
            assert r.record_type in ("expense", "transfer")

    def test_positive_amount_is_income(self) -> None:
        records = [
            BudgetBakersWalletClient._parse_record(item)
            for item in self._load_records()
        ]
        incomes = [r for r in records if r.amount.value > 0]
        for r in incomes:
            assert r.record_type in ("income", "transfer")

    def test_parses_transfer_record(self) -> None:
        records = [
            BudgetBakersWalletClient._parse_record(item)
            for item in self._load_records()
        ]
        transfers = [r for r in records if r.record_type == "transfer"]
        assert len(transfers) > 0
        for r in transfers:
            assert r.transfer is not None
            assert r.transfer.type
            if r.transfer.mirror_record is not None:
                assert r.transfer.mirror_record.id

    def test_parses_counter_party(self) -> None:
        records = [
            BudgetBakersWalletClient._parse_record(item)
            for item in self._load_records()
        ]
        with_cp = [r for r in records if r.counter_party is not None]
        assert len(with_cp) > 0
        assert all(isinstance(r.counter_party, str) for r in with_cp)

    def test_payment_type_is_payment_method_not_direction(self) -> None:
        records = [
            BudgetBakersWalletClient._parse_record(item)
            for item in self._load_records()
        ]
        payment_types = {r.payment_type for r in records if r.payment_type}
        assert "debit_card" in payment_types
        assert "credit" not in payment_types
        for pt in payment_types:
            assert pt in ("debit_card", "transfer")


# ── batch create response parsing ─────────────────────────────────────


class TestBatchCreateParsing200:
    def test_flat_list_is_parsed_as_all_success(self) -> None:
        data = _load_json("create_response_200.json")
        assert isinstance(data, list)
        result = BudgetBakersWalletClient.parse_batch_create_response(
            raw_response=data  # type: ignore[arg-type]
        )
        assert result.all_succeeded
        assert len(result.items) == 1
        item = result.items[0]
        assert item.index == 0
        assert item.status == 200
        assert item.record_id == "rec_new_01"
        assert item.error_code is None
        assert item.error_message is None

    def test_empty_list_is_empty_result(self) -> None:
        result = BudgetBakersWalletClient.parse_batch_create_response(
            raw_response=[]
        )
        assert len(result.items) == 0


class TestBatchCreateParsing207:
    def test_mixed_response_parses_per_index_results(self) -> None:
        data = _load_json("create_response_207.json")
        assert isinstance(data, list)
        result = BudgetBakersWalletClient.parse_batch_create_response(
            raw_response=data  # type: ignore[arg-type]
        )
        assert not result.all_succeeded
        assert len(result.items) == 3

        assert result.items[0].index == 0
        assert result.items[0].status == 200
        assert result.items[0].record_id == "rec_new_01"
        assert result.items[0].is_success

        assert result.items[1].index == 1
        assert result.items[1].status == 422
        assert result.items[1].record_id is None
        assert not result.items[1].is_success
        assert result.items[1].is_validation_error
        assert result.items[1].error_code == "VALIDATION_ERROR"

        assert result.items[2].index == 2
        assert result.items[2].status == 200
        assert result.items[2].record_id == "rec_new_03"

    def test_succeeded_ids_returns_only_successes(self) -> None:
        data = _load_json("create_response_207.json")
        assert isinstance(data, list)
        result = BudgetBakersWalletClient.parse_batch_create_response(
            raw_response=data  # type: ignore[arg-type]
        )
        ids = result.succeeded_ids
        assert "rec_new_01" in ids
        assert "rec_new_03" in ids
        assert len(ids) == 2

    def test_failed_indices_returns_failure_positions(self) -> None:
        data = _load_json("create_response_207.json")
        assert isinstance(data, list)
        result = BudgetBakersWalletClient.parse_batch_create_response(
            raw_response=data  # type: ignore[arg-type]
        )
        assert result.failed_indices == (1,)


# ── rate-limit classification ─────────────────────────────────────────


class TestRateLimitClassification:
    def test_429_status_is_rate_limit(self) -> None:
        result = BudgetBakersWalletClient.classify_rate_limit(
            status_code=429,
        )
        assert result == "rate_limit"

    def test_200_status_is_not_rate_limit(self) -> None:
        result = BudgetBakersWalletClient.classify_rate_limit(
            status_code=200,
        )
        assert result is None

    def test_400_status_is_not_rate_limit(self) -> None:
        result = BudgetBakersWalletClient.classify_rate_limit(
            status_code=400,
        )
        assert result is None

    def test_rate_limit_error_code_in_body(self) -> None:
        result = BudgetBakersWalletClient.classify_rate_limit(
            status_code=400,
            response_body={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "..."}},
        )
        assert result == "rate_limit"

    def test_429_fixture_is_classified_as_rate_limit(self) -> None:
        data = _load_json("create_response_429.json")
        assert isinstance(data, dict)
        result = BudgetBakersWalletClient.classify_rate_limit(
            response_body=data,  # type: ignore[arg-type]
            status_code=429,
        )
        assert result == "rate_limit"

    def test_400_fixture_is_not_rate_limit(self) -> None:
        data = _load_json("create_response_400.json")
        assert isinstance(data, dict)
        result = BudgetBakersWalletClient.classify_rate_limit(
            response_body=data,  # type: ignore[arg-type]
            status_code=400,
        )
        assert result is None


# ── CreateRecordRequest payload generation ────────────────────────────


class TestCreateRecordRequestPayload:
    def test_minimal_payload_has_required_fields(self) -> None:
        req = CreateRecordRequest(
            account_id="acct_01",
            category_id="cat_01",
            amount_value=-42.30,
            currency_code="USD",
            record_date="2025-07-15",
        )
        payload = req.as_payload()
        assert payload["accountId"] == "acct_01"
        assert payload["categoryId"] == "cat_01"
        assert payload["amount"]["value"] == -42.30
        assert payload["amount"]["currencyCode"] == "USD"
        assert payload["recordDate"] == "2025-07-15"

    def test_category_and_currency_are_optional_in_the_rest_contract(self) -> None:
        payload = CreateRecordRequest(
            account_id="acct_01",
            amount_value=50.0,
            record_date="2025-07-15T00:00:00Z",
        ).as_payload()
        assert "categoryId" not in payload
        assert payload["amount"] == {"value": 50.0}

    def test_full_payload_includes_optional_fields(self) -> None:
        req = CreateRecordRequest(
            account_id="acct_01",
            category_id="cat_01",
            amount_value=-42.30,
            currency_code="USD",
            record_date="2025-07-15",
            note="Weekly shop",
            counter_party="GROCERY MART",
            label_ids=("lbl_03",),
            payment_type="debit_card",
            record_state="cleared",
        )
        payload = req.as_payload()
        assert payload["note"] == "Weekly shop"
        assert payload["counterParty"] == "GROCERY MART"
        assert payload["labelIds"] == ["lbl_03"]
        assert payload["paymentType"] == "debit_card"
        assert "recordType" not in payload
        assert payload["recordState"] == "cleared"
        assert "transfer" not in payload

    def test_transfer_payload_includes_transfer_object(self) -> None:
        req = CreateRecordRequest(
            account_id="acct_01",
            category_id="cat_05",
            amount_value=-1000.0,
            currency_code="USD",
            record_date="2025-07-01",
            transfer_account_id="acct_02",
            transfer_pairing_mode="new",
            transfer_counter_amount_value=1000.0,
            transfer_counter_amount_currency_code="USD",
        )
        payload = req.as_payload()
        assert payload["transfer"]["accountId"] == "acct_02"
        assert payload["transfer"]["pairingMode"] == "new"
        assert payload["transfer"]["counterAmount"]["value"] == 1000.0
        assert payload["transfer"]["counterAmount"]["currencyCode"] == "USD"

    def test_transfer_shape_rejects_unsupported_or_incomplete_modes(self) -> None:
        with pytest.raises(ValueError, match="new transfers"):
            CreateRecordRequest(
                account_id="acct_01",
                amount_value=-10.0,
                record_date="2025-07-01T00:00:00Z",
                transfer_pairing_mode="new",
            )
        with pytest.raises(ValueError, match="new, existing, or unpaired"):
            CreateRecordRequest(
                account_id="acct_01",
                amount_value=-10.0,
                record_date="2025-07-01T00:00:00Z",
                transfer_pairing_mode="manual",
            )


# ── redaction — no secrets in fixtures ─────────────────────────────────


class TestFixtureRedaction:
    """Ensure no secrets leak into committed fixture files."""

    SECRET_PATTERNS = [
        "Bearer ",
        "api_key",
        "password",
        "secret",
        "@gmail.com",
        "@example.com",
    ]

    @pytest.mark.parametrize("fixture_name", [
        "accounts.json",
        "categories.json",
        "labels.json",
        "record_rules.json",
        "records.json",
        "create_response_200.json",
        "create_response_207.json",
        "create_response_400.json",
        "create_response_429.json",
    ])
    def test_fixture_contains_no_secrets(self, fixture_name: str) -> None:
        raw = (FIXTURE_DIR / fixture_name).read_text()
        lower = raw.lower()
        for pattern in self.SECRET_PATTERNS:
            assert pattern.lower() not in lower, (
                f"Secret pattern {pattern!r} found in {fixture_name}"
            )

"""Tests for the Money value object."""

from __future__ import annotations

import pytest

from wallet_v2.domain.money import CurrencyMismatch, InvalidMoney, Money


class TestMoneyConstruction:
    def test_accepts_non_negative_int_minor_and_uppercase_currency(self) -> None:
        m = Money(minor=100, currency="USD")
        assert m.minor == 100
        assert m.currency == "USD"

    def test_zero_minor_is_allowed_money_is_zero_capable(self) -> None:
        m = Money(minor=0, currency="USD")
        assert m.is_zero()
        assert not m.is_positive()

    def test_positive_minor_is_positive(self) -> None:
        assert Money(minor=1, currency="EUR").is_positive()
        assert not Money(minor=1, currency="EUR").is_zero()

    def test_negative_minor_rejected(self) -> None:
        with pytest.raises(InvalidMoney):
            Money(minor=-1, currency="USD")

    def test_bool_minor_rejected_even_though_int_subclass(self) -> None:
        with pytest.raises(InvalidMoney):
            Money(minor=True, currency="USD")  # type: ignore[arg-type]

    def test_non_int_minor_rejected_float_decimal_banned(self) -> None:
        with pytest.raises(InvalidMoney):
            Money(minor=1.5, currency="USD")  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_currency", ["usd", "US", "USDD", "US1", "U"])
    def test_malformed_currency_rejected(self, bad_currency: str) -> None:
        with pytest.raises(InvalidMoney):
            Money(minor=100, currency=bad_currency)

    def test_non_string_currency_rejected(self) -> None:
        with pytest.raises(InvalidMoney):
            Money(minor=100, currency=123)  # type: ignore[arg-type]


class TestMoneyArithmetic:
    def test_add_same_currency_returns_sum_of_minor_units(self) -> None:
        assert Money(100, "USD") + Money(200, "USD") == Money(300, "USD")

    def test_add_cross_currency_raises_currency_mismatch(self) -> None:
        with pytest.raises(CurrencyMismatch):
            _ = Money(100, "USD") + Money(100, "EUR")

    def test_add_with_non_money_returns_not_implemented(self) -> None:
        assert Money(100, "USD").__add__(42) is NotImplemented


class TestMoneyComparison:
    def test_equality_compares_minor_and_currency(self) -> None:
        assert Money(100, "USD") == Money(100, "USD")
        assert Money(100, "USD") != Money(101, "USD")
        assert Money(100, "USD") != Money(100, "EUR")

    def test_equality_against_non_money_is_not_implemented(self) -> None:
        assert Money(100, "USD").__eq__(100) is NotImplemented

    def test_lt_and_le_same_currency(self) -> None:
        assert Money(50, "USD") < Money(100, "USD")
        assert Money(50, "USD") <= Money(50, "USD")
        assert not (Money(100, "USD") < Money(50, "USD"))

    def test_lt_cross_currency_raises(self) -> None:
        with pytest.raises(CurrencyMismatch):
            _ = Money(50, "USD") < Money(100, "EUR")


class TestMoneyHashing:
    def test_hash_consistent_with_equality(self) -> None:
        a = Money(100, "USD")
        b = Money(100, "USD")
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_different_money_hashes_differ(self) -> None:
        assert hash(Money(100, "USD")) != hash(Money(100, "EUR"))


class TestMoneySerialization:
    def test_roundtrip_to_dict_and_from_dict_preserves_value(self) -> None:
        original = Money(12345, "USD")
        restored = Money.from_dict(original.to_dict())
        assert restored == original
        assert isinstance(restored.minor, int)
        assert not isinstance(restored.minor, bool)

    def test_from_dict_rejects_non_dict(self) -> None:
        with pytest.raises(InvalidMoney):
            Money.from_dict("not a dict")  # type: ignore[arg-type]

    def test_from_dict_rejects_missing_keys(self) -> None:
        with pytest.raises(InvalidMoney):
            Money.from_dict({"minor": 100})  # type: ignore[arg-type]


class TestMoneyRepresentation:
    def test_str_includes_currency_and_minor(self) -> None:
        assert str(Money(100, "USD")) == "USD 100"

    def test_repr_is_safe_and_informative(self) -> None:
        assert "Money(minor=100" in repr(Money(100, "USD"))

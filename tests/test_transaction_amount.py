"""Tests for the strictly-positive TransactionAmount value object."""

from __future__ import annotations

import pytest

from wallet_v2.domain.money import CurrencyMismatch, InvalidMoney, Money
from wallet_v2.domain.transaction import (
    InvalidTransactionAmount,
    TransactionAmount,
)


class TestTransactionAmountConstruction:
    def test_accepts_strictly_positive_money(self) -> None:
        t = TransactionAmount(money=Money(100, "USD"))
        assert t.minor == 100
        assert t.currency == "USD"

    def test_rejects_zero_money(self) -> None:
        with pytest.raises(InvalidTransactionAmount):
            TransactionAmount(money=Money(0, "USD"))

    def test_money_negative_rejected_at_money_layer(self) -> None:
        with pytest.raises(InvalidMoney):
            Money(-1, "USD")

    def test_rejects_non_money_input(self) -> None:
        with pytest.raises(InvalidTransactionAmount):
            TransactionAmount(money=100)  # type: ignore[arg-type]


class TestTransactionAmountEquality:
    def test_equal_when_underlying_money_equal(self) -> None:
        assert TransactionAmount(Money(100, "USD")) == TransactionAmount(
            Money(100, "USD")
        )

    def test_not_equal_when_minor_or_currency_differ(self) -> None:
        assert TransactionAmount(Money(100, "USD")) != TransactionAmount(
            Money(101, "USD")
        )
        assert TransactionAmount(Money(100, "USD")) != TransactionAmount(
            Money(100, "EUR")
        )

    def test_hash_consistent_with_equality(self) -> None:
        a = TransactionAmount(Money(100, "USD"))
        b = TransactionAmount(Money(100, "USD"))
        assert hash(a) == hash(b)
        assert {a, b} == {a}


class TestTransactionAmountComparison:
    def test_lt_same_currency(self) -> None:
        assert TransactionAmount(Money(50, "USD")) < TransactionAmount(
            Money(100, "USD")
        )

    def test_lt_cross_currency_raises(self) -> None:
        with pytest.raises(CurrencyMismatch):
            _ = TransactionAmount(Money(50, "USD")) < TransactionAmount(
                Money(100, "EUR")
            )


class TestTransactionAmountSerialization:
    def test_roundtrip_to_dict_and_from_dict(self) -> None:
        original = TransactionAmount(Money(12345, "USD"))
        restored = TransactionAmount.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_rejects_zero(self) -> None:
        with pytest.raises(InvalidTransactionAmount):
            TransactionAmount.from_dict({"minor": 0, "currency": "USD"})

    def test_from_dict_rejects_non_dict(self) -> None:
        with pytest.raises(InvalidTransactionAmount):
            TransactionAmount.from_dict("nope")  # type: ignore[arg-type]

"""Positive-magnitude transaction amount value object.

:class:`~wallet_v2.domain.money.Money` is an *unsigned magnitude* and may
legitimately be zero — for example, a placeholder candidate while a source
is being triaged. A *transaction*, however, must carry a strictly positive
magnitude: a zero-value transaction has no financial meaning and a negative
one is modeled by combining :class:`Money` with a
:class:`~wallet_v2.domain.enums.TransactionDirection`.

:class:`TransactionAmount` wraps a :class:`Money` value and enforces the
strictly-positive invariant at construction. The domain layer uses this type
wherever a transaction is being modeled (candidates, import commands,
receipts), and uses bare :class:`Money` where a magnitude may legitimately
be zero (e.g., a fee component that was not assessed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wallet_v2.domain.money import CurrencyMismatch, InvalidMoney, Money


class InvalidTransactionAmount(ValueError):
    """Raised when a :class:`TransactionAmount` is constructed with bad inputs."""


@dataclass(frozen=True, slots=True)
class TransactionAmount:
    """A strictly-positive monetary magnitude paired with a currency.

    Attributes:
        money: A :class:`Money` value whose ``minor`` is greater than zero.
    """

    money: Money

    def __post_init__(self) -> None:
        if not isinstance(self.money, Money):
            raise InvalidTransactionAmount(
                f"money must be Money, got {type(self.money).__name__}"
            )
        if not self.money.is_positive():
            raise InvalidTransactionAmount(
                f"transaction magnitude must be > 0, got {self.money}"
            )

    @property
    def minor(self) -> int:
        return self.money.minor

    @property
    def currency(self) -> str:
        return self.money.currency

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TransactionAmount):
            return NotImplemented
        return self.money == other.money

    def __hash__(self) -> int:
        return hash(self.money)

    def __lt__(self, other: "TransactionAmount") -> bool:
        if not isinstance(other, TransactionAmount):
            return NotImplemented  # type: ignore[return-value]
        if self.money.currency != other.money.currency:
            raise CurrencyMismatch(
                f"cannot compare {self.money.currency} and {other.money.currency}"
            )
        return self.money < other.money

    def __str__(self) -> str:
        return str(self.money)

    def __repr__(self) -> str:
        return f"TransactionAmount(money={self.money!r})"

    def to_dict(self) -> dict[str, Any]:
        return self.money.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransactionAmount":
        if not isinstance(data, dict):
            raise InvalidTransactionAmount(
                f"expected dict, got {type(data).__name__}"
            )
        try:
            money = Money.from_dict(data)
        except InvalidMoney as exc:
            raise InvalidTransactionAmount(str(exc)) from exc
        return cls(money=money)

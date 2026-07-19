"""Money value object.

Money is stored as a non-negative integer count of minor units (cents for
2-decimal currencies) plus an ISO 4217 currency code. The minor-unit
representation avoids binary floating-point error: every monetary amount that
flows through Wallet V2 — candidates, import commands, receipts, and
reconciliation — is expressed in minor units.

Direction (debit/credit) is modeled separately by
:class:`~wallet_v2.domain.enums.TransactionDirection`; ``Money`` itself is an
unsigned magnitude. A negative ``minor`` is rejected at construction time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class InvalidMoney(ValueError):
    """Raised when a ``Money`` value is constructed with invalid inputs."""


class CurrencyMismatch(ValueError):
    """Raised when an operation is attempted across two different currencies."""


_CURRENCY_LEN = 3


@dataclass(frozen=True, slots=True)
class Money:
    """An unsigned monetary amount in minor units.

    Attributes:
        minor: Non-negative integer count of minor currency units.
        currency: Uppercase 3-letter ISO 4217 currency code.
    """

    minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.minor, int) or isinstance(self.minor, bool):
            raise InvalidMoney(f"minor must be int, got {type(self.minor).__name__}")
        if self.minor < 0:
            raise InvalidMoney(f"minor must be non-negative, got {self.minor}")
        if not isinstance(self.currency, str):
            raise InvalidMoney(
                f"currency must be str, got {type(self.currency).__name__}"
            )
        if len(self.currency) != _CURRENCY_LEN:
            raise InvalidMoney(
                f"currency must be {_CURRENCY_LEN} letters, got {self.currency!r}"
            )
        if self.currency != self.currency.upper():
            raise InvalidMoney(f"currency must be uppercase, got {self.currency!r}")
        if not self.currency.isalpha():
            raise InvalidMoney(f"currency must be alphabetic, got {self.currency!r}")

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented  # type: ignore[return-value]
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"cannot add {self.currency} and {other.currency}"
            )
        return Money(self.minor + other.minor, self.currency)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.minor == other.minor and self.currency == other.currency

    def __hash__(self) -> int:
        return hash((self.minor, self.currency))

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented  # type: ignore[return-value]
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"cannot compare {self.currency} and {other.currency}"
            )
        return self.minor < other.minor

    def __le__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented  # type: ignore[return-value]
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"cannot compare {self.currency} and {other.currency}"
            )
        return self.minor <= other.minor

    def __str__(self) -> str:
        return f"{self.currency} {self.minor}"

    def __repr__(self) -> str:
        return f"Money(minor={self.minor}, currency={self.currency!r})"

    def is_zero(self) -> bool:
        return self.minor == 0

    def is_positive(self) -> bool:
        return self.minor > 0

    def to_dict(self) -> dict[str, Any]:
        return {"minor": self.minor, "currency": self.currency}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Money":
        if not isinstance(data, dict):
            raise InvalidMoney(f"expected dict, got {type(data).__name__}")
        missing = {"minor", "currency"} - data.keys()
        if missing:
            raise InvalidMoney(f"missing keys: {sorted(missing)}")
        return cls(minor=data["minor"], currency=data["currency"])

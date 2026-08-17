"""Money as integer minor units plus a currency code.

Floats are banned and a bare decimal without a currency is banned — see ADR-0004.
This module is pure: no Django imports, so it is unit-testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

__all__ = ["Money", "MoneyProxy", "CurrencyMismatch"]


class CurrencyMismatch(ValueError):
    """Raised when two amounts in different currencies are combined."""


@dataclass(frozen=True, slots=True, order=False)
class Money:
    """An exact monetary amount.

    ``amount_minor`` is always in the currency's smallest unit: cents for USD,
    rials for IRR (exponent 0), 1e-6 USDT. Never a float, never rounded here.
    """

    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise TypeError(
                f"amount_minor must be an int, got {type(self.amount_minor).__name__}. "
                "Floats are not permitted for money."
            )
        if not self.currency or len(self.currency) > 8:
            raise ValueError(f"Invalid currency code: {self.currency!r}")
        object.__setattr__(self, "currency", self.currency.upper())

    # -- construction ------------------------------------------------------
    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    @classmethod
    def from_major(cls, major: Decimal | str | int, currency: str, exponent: int) -> Money:
        """Build from a human-facing amount, e.g. ``"149.00"`` USD with exponent 2."""
        if isinstance(major, float):
            raise TypeError("Refusing to build Money from a float; pass Decimal or str.")
        value = Decimal(str(major)) * (Decimal(10) ** exponent)
        return cls(int(value.to_integral_value(rounding=ROUND_HALF_EVEN)), currency)

    def to_major(self, exponent: int) -> Decimal:
        return Decimal(self.amount_minor) / (Decimal(10) ** exponent)

    # -- arithmetic --------------------------------------------------------
    def _check(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"Cannot combine {self.currency} with {other.currency}. "
                "An order carries exactly one currency."
            )

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __mul__(self, quantity: int) -> Money:
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise TypeError("Money may only be multiplied by an int quantity.")
        return Money(self.amount_minor * quantity, self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> Money:
        return Money(-self.amount_minor, self.currency)

    def apply_rate(self, rate: Decimal | str) -> Money:
        """Apply a ratio (e.g. a 15% discount) with banker's rounding.

        Applied once per line and then summed — never to a total (ADR-0004).
        """
        result = Decimal(self.amount_minor) * Decimal(str(rate))
        return Money(int(result.to_integral_value(rounding=ROUND_HALF_EVEN)), self.currency)

    # -- comparison --------------------------------------------------------
    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor < other.amount_minor

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor <= other.amount_minor

    def __gt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor > other.amount_minor

    def __ge__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor >= other.amount_minor

    @property
    def is_zero(self) -> bool:
        return self.amount_minor == 0

    @property
    def is_negative(self) -> bool:
        return self.amount_minor < 0

    def __str__(self) -> str:  # debugging only — user output goes through formatting.py
        return f"{self.amount_minor} {self.currency}"


def sum_money(amounts: list[Money], currency: str) -> Money:
    """Sum a list of amounts, returning zero in ``currency`` when empty."""
    total = Money.zero(currency)
    for amount in amounts:
        total = total + amount
    return total


class MoneyProxy:
    """Descriptor exposing two model columns as a single :class:`Money`.

    Django has no composite field, so models declare the columns explicitly and
    attach this descriptor. Assigning a ``Money`` writes both columns at once, which
    is what stops anyone storing an amount without its currency::

        class Order(models.Model):
            total_amount_minor = models.BigIntegerField(default=0)
            currency = CurrencyCodeField()
            total = MoneyProxy("total_amount_minor", "currency")
    """

    def __init__(self, amount_field: str, currency_field: str) -> None:
        self.amount_field = amount_field
        self.currency_field = currency_field

    def __get__(self, instance: Any, owner: type | None = None) -> Money | MoneyProxy | None:
        if instance is None:
            return self
        amount = getattr(instance, self.amount_field)
        currency = getattr(instance, self.currency_field)
        if amount is None or not currency:
            return None
        return Money(amount, currency)

    def __set__(self, instance: Any, value: Money | None) -> None:
        if value is None:
            setattr(instance, self.amount_field, None)
            return
        if not isinstance(value, Money):
            raise TypeError(f"Expected Money, got {type(value).__name__}.")
        setattr(instance, self.amount_field, value.amount_minor)
        setattr(instance, self.currency_field, value.currency)

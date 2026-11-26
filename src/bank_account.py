from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from enum import Enum
from threading import Lock
from uuid import uuid4


class AccountFrozenError(Exception):
    pass


class AccountClosedError(Exception):
    pass


class InvalidOperationError(ValueError):
    pass


class InsufficientFundsError(Exception):
    pass


class AccountStatus(str, Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class AbstractAccount(ABC):
    def __init__(
        self, account_number: str, owner: str, balance: Decimal, status: AccountStatus
    ) -> None:
        self._account_number = account_number
        self._owner = owner
        self._balance = balance
        self._status = status

    @property
    def account_number(self) -> str:
        return self._account_number

    @property
    def balance(self) -> Decimal:
        return self._balance

    @property
    def status(self) -> AccountStatus:
        return self._status

    @abstractmethod
    def deposit(self, amount: Decimal | int | float | str) -> None:
        raise NotImplementedError

    @abstractmethod
    def withdraw(self, amount: Decimal | int | float | str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_account_info(self) -> dict[str, str | Decimal]:
        raise NotImplementedError


class BankAccount(AbstractAccount):
    CURRENCIES = frozenset({"RUB", "USD", "EUR", "KZT", "CNY"})
    _issued_numbers: set[str] = set()
    _number_lock = Lock()

    def __init__(
        self,
        owner: str,
        balance: Decimal | int | float | str = 0,
        currency: str = "RUB",
        status: AccountStatus | str = AccountStatus.ACTIVE,
        account_number: str | None = None,
    ) -> None:
        if not isinstance(owner, str) or not owner.strip():
            raise InvalidOperationError("Owner must be a non-empty name")
        if not isinstance(currency, str) or currency not in self.CURRENCIES:
            raise InvalidOperationError("Unsupported currency")
        try:
            account_status = AccountStatus(status)
        except (TypeError, ValueError) as error:
            raise InvalidOperationError("Unknown account status") from error

        opening_balance = self._validate_amount(balance, allow_zero=True)
        number = self._reserve_number(account_number)
        super().__init__(number, owner.strip(), opening_balance, account_status)
        self._currency = currency

    @property
    def currency(self) -> str:
        return self._currency

    @classmethod
    def _reserve_number(cls, number: str | None) -> str:
        if number is not None:
            if not isinstance(number, str) or len(number) < 4:
                raise InvalidOperationError("Account number must have at least four digits")
            if not number.isascii() or not number.isdecimal():
                raise InvalidOperationError("Account number must contain only ASCII digits")

        with cls._number_lock:
            if number is None:
                number = f"{uuid4().int % 10**16:016d}"
                while number in cls._issued_numbers:
                    number = f"{uuid4().int % 10**16:016d}"
            elif number in cls._issued_numbers:
                raise InvalidOperationError("Account number is already in use")

            cls._issued_numbers.add(number)
            return number

    @staticmethod
    def _validate_amount(
        amount: Decimal | int | float | str, *, allow_zero: bool = False
    ) -> Decimal:
        if isinstance(amount, bool) or not isinstance(amount, (Decimal, int, float, str)):
            raise InvalidOperationError("Amount must be numeric")
        try:
            value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        except (InvalidOperation, ValueError) as error:
            raise InvalidOperationError("Amount must be numeric") from error

        if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
            requirement = "non-negative" if allow_zero else "positive"
            raise InvalidOperationError(f"Amount must be finite and {requirement}")
        return value

    def _require_active(self) -> None:
        if self.status is AccountStatus.FROZEN:
            raise AccountFrozenError("Account is frozen")
        if self.status is AccountStatus.CLOSED:
            raise AccountClosedError("Account is closed")

    def deposit(self, amount: Decimal | int | float | str) -> None:
        self._require_active()
        self._balance += self._validate_amount(amount)

    def withdraw(self, amount: Decimal | int | float | str) -> None:
        self._require_active()
        value = self._validate_amount(amount)
        if value > self._balance:
            raise InsufficientFundsError("Insufficient funds")
        self._balance -= value

    def get_account_info(self) -> dict[str, str | Decimal]:
        return {
            "account_type": type(self).__name__,
            "account_number": self.account_number,
            "owner": self._owner,
            "status": self.status.value,
            "balance": self.balance,
            "currency": self.currency,
        }

    def __str__(self) -> str:
        return (
            f"{type(self).__name__} | {self._owner} | ****{self.account_number[-4:]} | "
            f"{self.status.value} | {self.balance} {self.currency}"
        )

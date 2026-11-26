from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
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
    def get_account_info(self) -> dict[str, str | Decimal | dict[str, Decimal]]:
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
        self._operation_guard: Callable[[], None] | None = None

    @property
    def currency(self) -> str:
        return self._currency

    @property
    def total_balance(self) -> Decimal:
        return self.balance

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
        amount: Decimal | int | float | str,
        *,
        allow_zero: bool = False,
        allow_negative: bool = False,
    ) -> Decimal:
        if isinstance(amount, bool) or not isinstance(amount, (Decimal, int, float, str)):
            raise InvalidOperationError("Amount must be numeric")
        try:
            value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        except (InvalidOperation, ValueError) as error:
            raise InvalidOperationError("Amount must be numeric") from error

        if not value.is_finite():
            raise InvalidOperationError("Amount must be finite")
        if value < 0 and not allow_negative:
            raise InvalidOperationError("Amount cannot be negative")
        if value == 0 and not allow_zero:
            raise InvalidOperationError("Amount cannot be zero")
        return value

    def _require_active(self) -> None:
        if self._operation_guard is not None:
            self._operation_guard()
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

    def get_account_info(self) -> dict[str, str | Decimal | dict[str, Decimal]]:
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


class SavingsAccount(BankAccount):
    def __init__(
        self,
        owner: str,
        balance: Decimal | int | float | str = 0,
        currency: str = "RUB",
        status: AccountStatus | str = AccountStatus.ACTIVE,
        account_number: str | None = None,
        *,
        min_balance: Decimal | int | float | str = 0,
        monthly_interest_rate: Decimal | int | float | str = "0.01",
    ) -> None:
        self._min_balance = self._validate_amount(min_balance, allow_zero=True)
        self._monthly_interest_rate = self._validate_amount(
            monthly_interest_rate, allow_zero=True
        )
        opening_balance = self._validate_amount(balance, allow_zero=True)
        if opening_balance < self.min_balance:
            raise InvalidOperationError("Opening balance is below the minimum balance")
        super().__init__(owner, opening_balance, currency, status, account_number)

    @property
    def min_balance(self) -> Decimal:
        return self._min_balance

    @property
    def monthly_interest_rate(self) -> Decimal:
        return self._monthly_interest_rate

    def withdraw(self, amount: Decimal | int | float | str) -> None:
        self._require_active()
        value = self._validate_amount(amount)
        if value > self.balance - self.min_balance:
            raise InsufficientFundsError("Withdrawal would breach the minimum balance")
        self._balance -= value

    def apply_monthly_interest(self) -> Decimal:
        self._require_active()
        interest = self.balance * self.monthly_interest_rate
        self._balance += interest
        return interest

    def get_account_info(self) -> dict[str, str | Decimal | dict[str, Decimal]]:
        return {
            **super().get_account_info(),
            "min_balance": self.min_balance,
            "monthly_interest_rate": self.monthly_interest_rate,
        }

    def __str__(self) -> str:
        return (
            f"{super().__str__()} | minimum {self.min_balance} {self.currency} | "
            f"monthly interest {self.monthly_interest_rate:.2%}"
        )


class PremiumAccount(BankAccount):
    def __init__(
        self,
        owner: str,
        balance: Decimal | int | float | str = 0,
        currency: str = "RUB",
        status: AccountStatus | str = AccountStatus.ACTIVE,
        account_number: str | None = None,
        *,
        withdrawal_limit: Decimal | int | float | str = 100_000,
        overdraft_limit: Decimal | int | float | str = 10_000,
        withdrawal_fee: Decimal | int | float | str = 50,
    ) -> None:
        self._withdrawal_limit = self._validate_amount(withdrawal_limit)
        self._overdraft_limit = self._validate_amount(overdraft_limit, allow_zero=True)
        self._withdrawal_fee = self._validate_amount(withdrawal_fee, allow_zero=True)
        super().__init__(owner, balance, currency, status, account_number)

    def withdraw(self, amount: Decimal | int | float | str) -> None:
        self._require_active()
        value = self._validate_amount(amount)
        if value > self._withdrawal_limit:
            raise InvalidOperationError("Withdrawal exceeds the per-operation limit")
        debit = value + self._withdrawal_fee
        if debit > self.balance + self._overdraft_limit:
            raise InsufficientFundsError("Withdrawal with fee exceeds the overdraft limit")
        self._balance -= debit

    def get_account_info(self) -> dict[str, str | Decimal | dict[str, Decimal]]:
        return {
            **super().get_account_info(),
            "withdrawal_limit": self._withdrawal_limit,
            "overdraft_limit": self._overdraft_limit,
            "withdrawal_fee": self._withdrawal_fee,
        }

    def __str__(self) -> str:
        return (
            f"{super().__str__()} | withdrawal limit {self._withdrawal_limit} {self.currency} | "
            f"overdraft {self._overdraft_limit} {self.currency} | "
            f"fee {self._withdrawal_fee} {self.currency}"
        )


class InvestmentAccount(BankAccount):
    ASSET_TYPES = ("stocks", "bonds", "etf")

    def __init__(
        self,
        owner: str,
        balance: Decimal | int | float | str = 0,
        currency: str = "RUB",
        status: AccountStatus | str = AccountStatus.ACTIVE,
        account_number: str | None = None,
    ) -> None:
        super().__init__(owner, balance, currency, status, account_number)
        self._portfolio = dict.fromkeys(self.ASSET_TYPES, Decimal(0))

    @property
    def portfolio(self) -> dict[str, Decimal]:
        return self._portfolio.copy()

    @property
    def total_balance(self) -> Decimal:
        return self.balance + sum(self._portfolio.values(), Decimal(0))

    def invest(self, asset_type: str, amount: Decimal | int | float | str) -> None:
        self._require_active()
        if asset_type not in self.ASSET_TYPES:
            raise InvalidOperationError("Unknown asset type")
        value = self._validate_amount(amount)
        if value > self.balance:
            raise InsufficientFundsError("Insufficient uninvested funds")
        asset_balance = self._portfolio[asset_type] + value
        self._balance -= value
        self._portfolio[asset_type] = asset_balance

    def withdraw(self, amount: Decimal | int | float | str) -> None:
        self._require_active()
        value = self._validate_amount(amount)
        if value > self.balance:
            raise InsufficientFundsError("Only uninvested funds are available for withdrawal")
        self._balance -= value

    def project_yearly_growth(
        self, growth_rates: Mapping[str, Decimal | int | float | str]
    ) -> Decimal:
        if not isinstance(growth_rates, Mapping):
            raise InvalidOperationError("Growth rates must map asset types to rates")
        rates = {}
        for asset_type, rate in growth_rates.items():
            if asset_type not in self.ASSET_TYPES:
                raise InvalidOperationError("Unknown asset type")
            rates[asset_type] = self._validate_amount(
                rate, allow_zero=True, allow_negative=True
            )

        growth = Decimal(0)
        for asset_type, amount in self._portfolio.items():
            if amount:
                if asset_type not in rates:
                    raise InvalidOperationError(f"Missing growth rate for {asset_type}")
                growth += amount * rates[asset_type]
        return growth

    def get_account_info(self) -> dict[str, str | Decimal | dict[str, Decimal]]:
        return {**super().get_account_info(), "portfolio": self.portfolio}

    def __str__(self) -> str:
        invested = sum(self._portfolio.values(), Decimal(0))
        return f"{super().__str__()} | portfolio {invested} {self.currency}"

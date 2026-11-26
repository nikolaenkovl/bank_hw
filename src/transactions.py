from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, DecimalException
from enum import Enum
from threading import Lock
from uuid import uuid4

from src.bank import NightOperationError
from src.bank_account import (
    AccountClosedError,
    AccountFrozenError,
    BankAccount,
    InsufficientFundsError,
    InvalidOperationError,
    PremiumAccount,
)


class TransactionType(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class TransactionStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRY_SCHEDULED = "retry_scheduled"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TransactionError:
    timestamp: datetime
    attempt: int
    reason: str


@dataclass(eq=False)
class Transaction:
    sender: BankAccount
    recipient: BankAccount
    amount: Decimal | int | float | str
    currency: str
    transaction_type: TransactionType = TransactionType.INTERNAL
    transaction_id: str = field(default_factory=lambda: uuid4().hex, init=False)
    status: TransactionStatus = field(default=TransactionStatus.CREATED, init=False)
    fee: Decimal = field(default=Decimal(0), init=False)
    credited_amount: Decimal | None = field(default=None, init=False)
    failure_reason: str | None = field(default=None, init=False)
    attempts: int = field(default=0, init=False)
    created_at: datetime = field(default_factory=datetime.now)
    scheduled_at: datetime | None = field(default=None, init=False)
    started_at: datetime | None = field(default=None, init=False)
    finished_at: datetime | None = field(default=None, init=False)
    errors: list[TransactionError] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.amount = BankAccount._validate_amount(self.amount)
        if not isinstance(self.currency, str) or self.currency not in BankAccount.CURRENCIES:
            raise InvalidOperationError("Unsupported transaction currency")
        try:
            self.transaction_type = TransactionType(self.transaction_type)
        except ValueError as error:
            raise InvalidOperationError("Unknown transaction type") from error


class TransactionQueue:
    def __init__(self, *, clock: Callable[[], datetime] = datetime.now) -> None:
        self._clock = clock
        self._pending: dict[str, tuple[Transaction, int, datetime]] = {}
        self._lock = Lock()

    def add(
        self,
        transaction: Transaction,
        *,
        priority: int = 0,
        scheduled_at: datetime | None = None,
    ) -> None:
        if type(priority) is not int:
            raise InvalidOperationError("Priority must be an integer")
        with self._lock:
            if transaction.status is not TransactionStatus.CREATED:
                raise InvalidOperationError("Transaction was already submitted")
            now = self._clock()
            due = scheduled_at if scheduled_at is not None else now
            if not isinstance(due, datetime) or (due.utcoffset() is None) != (
                now.utcoffset() is None
            ):
                raise InvalidOperationError("Scheduled time must match the queue clock")
            self._pending[transaction.transaction_id] = (transaction, priority, due)
            transaction.scheduled_at = due
            transaction.status = TransactionStatus.QUEUED

    def cancel(self, transaction_id: str) -> bool:
        with self._lock:
            entry = self._pending.get(transaction_id)
            if entry is None:
                return False
            now = self._clock()
            transaction, _, _ = self._pending.pop(transaction_id)
            transaction.status = TransactionStatus.CANCELLED
            transaction.failure_reason = "Cancelled"
            transaction.finished_at = now
            return True

    def _take_ready(self, now: datetime) -> tuple[Transaction, int] | None:
        with self._lock:
            entry = max(
                (entry for entry in self._pending.values() if entry[2] <= now),
                key=lambda entry: entry[1],
                default=None,
            )
            if entry is None:
                return None
            transaction, priority, _ = entry
            del self._pending[transaction.transaction_id]
            transaction.status = TransactionStatus.PROCESSING
            transaction.started_at = now
            transaction.attempts += 1
            return transaction, priority

    def _reschedule(self, transaction: Transaction, priority: int, due: datetime) -> None:
        with self._lock:
            transaction.scheduled_at = due
            transaction.status = TransactionStatus.RETRY_SCHEDULED
            self._pending[transaction.transaction_id] = (transaction, priority, due)


class TransactionProcessor:
    def __init__(
        self,
        queue: TransactionQueue,
        *,
        exchange_rates: Mapping[tuple[str, str], Decimal | int | float | str] | None = None,
        external_fee_rate: Decimal | int | float | str = "0.01",
        max_attempts: int = 3,
        retry_delay: timedelta = timedelta(hours=1),
    ) -> None:
        if type(max_attempts) is not int or max_attempts < 1:
            raise InvalidOperationError("At least one attempt is required")
        if not isinstance(retry_delay, timedelta) or retry_delay <= timedelta(0):
            raise InvalidOperationError("Retry delay must be positive")
        self._queue = queue
        self._exchange_rates = {
            pair: BankAccount._validate_amount(rate)
            for pair, rate in (exchange_rates or {}).items()
        }
        self._external_fee_rate = BankAccount._validate_amount(external_fee_rate, allow_zero=True)
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay

    def _transfer(self, transaction: Transaction) -> None:
        sender, recipient = transaction.sender, transaction.recipient
        if not isinstance(sender, BankAccount) or not isinstance(recipient, BankAccount):
            raise InvalidOperationError("Sender and recipient must be bank accounts")
        if sender is recipient:
            raise InvalidOperationError("Sender and recipient must be different accounts")
        if transaction.currency != sender.currency:
            raise InvalidOperationError("Transaction currency must match the sender's currency")

        amount = BankAccount._validate_amount(transaction.amount)
        fee = Decimal(0)
        if transaction.transaction_type is TransactionType.EXTERNAL:
            fee = amount * self._external_fee_rate

        credited = amount
        if sender.currency != recipient.currency:
            pair = (sender.currency, recipient.currency)
            rate = self._exchange_rates.get(pair)
            if rate is None:
                raise InvalidOperationError(f"Missing exchange rate for {pair[0]}/{pair[1]}")
            credited *= rate

        first, second = sorted((sender, recipient), key=id)
        with first._balance_lock, second._balance_lock:
            sender_balance = sender._balance_after_withdrawal(amount + fee)
            if sender_balance < 0 and not isinstance(sender, PremiumAccount):
                raise InsufficientFundsError("Only premium accounts allow overdrafts")
            recipient_balance = recipient._balance_after_deposit(credited)
            if isinstance(sender, PremiumAccount):
                fee += sender.withdrawal_fee
            sender._balance = sender_balance
            recipient._balance = recipient_balance
            transaction.fee = fee
            transaction.credited_amount = credited

    def process_ready(self) -> list[Transaction]:
        cutoff = self._queue._clock()
        processed = []
        while (entry := self._queue._take_ready(cutoff)) is not None:
            transaction, priority = entry
            try:
                self._transfer(transaction)
            except (
                AccountClosedError,
                AccountFrozenError,
                InsufficientFundsError,
                InvalidOperationError,
                DecimalException,
            ) as error:
                now = self._queue._clock()
                reason = str(error)
                transaction.errors.append(TransactionError(now, transaction.attempts, reason))
                transaction.failure_reason = reason
                if isinstance(error, NightOperationError) and transaction.attempts < self._max_attempts:
                    self._queue._reschedule(transaction, priority, now + self._retry_delay)
                else:
                    transaction.status = TransactionStatus.FAILED
                    transaction.finished_at = now
            else:
                transaction.status = TransactionStatus.COMPLETED
                transaction.failure_reason = None
                transaction.finished_at = self._queue._clock()
            processed.append(transaction)
        return processed

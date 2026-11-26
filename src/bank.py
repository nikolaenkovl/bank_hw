from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from functools import partial
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_bytes
from threading import Lock
from uuid import uuid4

from src.bank_account import (
    AccountClosedError,
    AccountStatus,
    BankAccount,
    InvalidOperationError,
)


class ClientStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class NightOperationError(InvalidOperationError):
    pass


class ClientBlockedError(InvalidOperationError):
    pass


class Client:
    def __init__(self, full_name: str, age: int, contacts: Mapping[str, str]) -> None:
        if not isinstance(full_name, str) or not full_name.strip():
            raise InvalidOperationError("Full name is required")
        if type(age) is not int or age < 18:
            raise InvalidOperationError("Client must be at least 18")
        if not isinstance(contacts, Mapping) or not contacts or any(
            not isinstance(key, str) or not key.strip()
            or not isinstance(value, str) or not value.strip()
            for key, value in contacts.items()
        ):
            raise InvalidOperationError("At least one valid contact is required")

        self.full_name = full_name.strip()
        self.age = age
        self.contacts = dict(contacts)
        self._client_id = uuid4().hex
        self._status = ClientStatus.ACTIVE
        self._account_numbers: list[str] = []
        self._registered = False

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def status(self) -> ClientStatus:
        return self._status

    @property
    def account_numbers(self) -> list[str]:
        return self._account_numbers.copy()


@dataclass(frozen=True)
class SuspiciousActivity:
    timestamp: datetime
    action: str
    client_id: str | None
    reason: str


@dataclass
class _Credentials:
    salt: bytes
    password_hash: bytes
    failed_attempts: int = 0


class Bank:
    def __init__(self, *, clock: Callable[[], datetime] = datetime.now) -> None:
        self._clock = clock
        self._clients: dict[str, Client] = {}
        self._credentials: dict[str, _Credentials] = {}
        self._accounts: dict[str, BankAccount] = {}
        self._account_owners: dict[str, str] = {}
        self._suspicious_activities: list[SuspiciousActivity] = []
        self._authentication_lock = Lock()

    @property
    def suspicious_activities(self) -> tuple[SuspiciousActivity, ...]:
        return tuple(self._suspicious_activities)

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> bytes:
        return pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)

    def _record_activity(
        self, action: str, client_id: str | None, reason: str, timestamp: datetime
    ) -> None:
        self._suspicious_activities.append(
            SuspiciousActivity(timestamp, action, client_id, reason)
        )

    def _require_business_hours(self, action: str, client_id: str | None) -> datetime:
        now = self._clock()
        if now.hour < 5:
            self._record_activity(action, client_id, "outside_business_hours", now)
            raise NightOperationError("Operations are unavailable from 00:00 until 05:00")
        return now

    def _get_client(self, client_id: str) -> Client:
        try:
            return self._clients[client_id]
        except KeyError as error:
            raise InvalidOperationError("Unknown client ID") from error

    def _require_active_client(self, client_id: str, action: str) -> None:
        now = self._require_business_hours(action, client_id)
        if self._get_client(client_id).status is ClientStatus.BLOCKED:
            self._record_activity(action, client_id, "blocked_client", now)
            raise ClientBlockedError("Client is blocked")

    def add_client(self, client: Client, password: str) -> str:
        if not isinstance(client, Client):
            raise InvalidOperationError("Expected a Client")
        self._require_business_hours("add_client", client.client_id)
        if not isinstance(password, str) or not password:
            raise InvalidOperationError("Password is required")

        salt = token_bytes(16)
        password_hash = self._hash_password(password, salt)
        with self._authentication_lock:
            if client._registered or client.client_id in self._clients:
                raise InvalidOperationError("Client is already registered")
            self._credentials[client.client_id] = _Credentials(salt, password_hash)
            self._clients[client.client_id] = client
            client._registered = True
        return client.client_id

    def authenticate_client(self, client_id: str, password: str) -> bool:
        with self._authentication_lock:
            return self._authenticate_client(client_id, password)

    def _authenticate_client(self, client_id: str, password: str) -> bool:
        action = "authenticate_client"
        now = self._require_business_hours(action, client_id)
        client = self._clients.get(client_id)
        if client is None or client.status is ClientStatus.BLOCKED:
            reason = "unknown_client" if client is None else "blocked_client"
            self._record_activity(action, client_id, reason, now)
            return False

        credentials = self._credentials[client_id]
        if isinstance(password, str) and compare_digest(
            credentials.password_hash, self._hash_password(password, credentials.salt)
        ):
            credentials.failed_attempts = 0
            return True

        credentials.failed_attempts += 1
        if credentials.failed_attempts == 3:
            client._status = ClientStatus.BLOCKED
            self._record_activity(action, client_id, "client_blocked", now)
        else:
            self._record_activity(action, client_id, "invalid_password", now)
        return False

    def open_account(
        self, client_id: str, account_type: type[BankAccount] = BankAccount, **options
    ) -> BankAccount:
        self._require_active_client(client_id, "open_account")
        client = self._get_client(client_id)
        if not isinstance(account_type, type) or not issubclass(account_type, BankAccount):
            raise InvalidOperationError("Expected a BankAccount subclass")

        account = account_type(client.full_name, **options)
        account._operation_guard = partial(
            self._require_active_client, client_id, "account_operation"
        )
        number = account.account_number
        self._accounts[number] = account
        self._account_owners[number] = client_id
        client._account_numbers.append(number)
        return account

    def _change_account_status(
        self, account_number: str, target: AccountStatus, action: str
    ) -> None:
        client_id = self._account_owners.get(account_number)
        self._require_business_hours(action, client_id)
        if client_id is None:
            raise InvalidOperationError("Unknown account number")
        account = self._accounts[account_number]
        if account.status is AccountStatus.CLOSED:
            raise AccountClosedError("Account is closed")
        if target is AccountStatus.ACTIVE and account.status is not AccountStatus.FROZEN:
            raise InvalidOperationError("Only a frozen account can be unfrozen")
        if target is AccountStatus.FROZEN and account.status is not AccountStatus.ACTIVE:
            raise InvalidOperationError("Only an active account can be frozen")
        account._status = target

    def close_account(self, account_number: str) -> None:
        self._change_account_status(account_number, AccountStatus.CLOSED, "close_account")

    def freeze_account(self, account_number: str) -> None:
        self._change_account_status(account_number, AccountStatus.FROZEN, "freeze_account")

    def unfreeze_account(self, account_number: str) -> None:
        self._change_account_status(account_number, AccountStatus.ACTIVE, "unfreeze_account")

    def search_accounts(
        self,
        *,
        client_id: str | None = None,
        account_number: str | None = None,
        status: AccountStatus | str | None = None,
        currency: str | None = None,
    ) -> list[BankAccount]:
        return [
            account
            for number, account in self._accounts.items()
            if (client_id is None or self._account_owners[number] == client_id)
            and (account_number is None or number == account_number)
            and (status is None or account.status == status)
            and (currency is None or account.currency == currency)
        ]

    def get_total_balance(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for account in self._accounts.values():
            currency = account.currency
            totals[currency] = totals.get(currency, Decimal(0)) + account.total_balance
        return totals

    def get_clients_ranking(self) -> dict[str, list[tuple[Client, Decimal]]]:
        balances: dict[str, dict[str, Decimal]] = {}
        for number, account in self._accounts.items():
            by_client = balances.setdefault(account.currency, {})
            owner = self._account_owners[number]
            by_client[owner] = by_client.get(owner, Decimal(0)) + account.total_balance

        return {
            currency: [
                (self._clients[client_id], total)
                for client_id, total in sorted(by_client.items(), key=lambda item: -item[1])
            ]
            for currency, by_client in balances.items()
        }

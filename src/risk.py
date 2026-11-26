from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from threading import Lock

from src.bank_account import InvalidOperationError


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskBlockedError(InvalidOperationError):
    pass


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    reasons: tuple[str, ...]


class RiskAnalyzer:
    LARGE_AMOUNTS = {
        "RUB": Decimal("100000"),
        "USD": Decimal("1000"),
        "EUR": Decimal("1000"),
        "KZT": Decimal("500000"),
        "CNY": Decimal("7000"),
    }
    FREQUENCY_LIMIT = 4
    FREQUENCY_WINDOW = timedelta(minutes=10)

    def __init__(self) -> None:
        self._recent: dict[str, deque[tuple[datetime, str]]] = {}
        self._known_recipients: dict[str, set[str]] = {}
        self._lock = Lock()

    def assess(
        self,
        *,
        sender_id: str,
        recipient_number: str,
        transaction_id: str,
        amount: Decimal,
        currency: str,
        now: datetime,
    ) -> RiskAssessment:
        with self._lock:
            recent = self._recent.setdefault(sender_id, deque())
            while recent and now - recent[0][0] >= self.FREQUENCY_WINDOW:
                recent.popleft()
            if all(previous_id != transaction_id for _, previous_id in recent):
                recent.append((now, transaction_id))
            signals = (
                (amount >= self.LARGE_AMOUNTS[currency], "large_amount", 3),
                (len(recent) >= self.FREQUENCY_LIMIT, "frequent_operations", 2),
                (recipient_number not in self._known_recipients.get(sender_id, ()),
                 "new_recipient", 1),
                (now.hour < 5, "night_operation", 2),
            )
            score = sum(weight for matched, _, weight in signals if matched)
            level = RiskLevel.HIGH if score >= 3 else RiskLevel.MEDIUM if score else RiskLevel.LOW
            return RiskAssessment(level, tuple(reason for matched, reason, _ in signals if matched))

    def record_success(self, sender_id: str, recipient_number: str) -> None:
        with self._lock:
            self._known_recipients.setdefault(sender_id, set()).add(recipient_number)

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock


class AuditLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class AuditEvent:
    timestamp: datetime
    level: AuditLevel
    action: str
    transaction_id: str
    sender_id: str
    recipient_id: str
    amount: str
    currency: str
    risk: str | None = None
    reasons: tuple[str, ...] = ()
    error: str | None = None
    detail: str | None = None


class AuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.file_error: OSError | None = None
        self._events: list[AuditEvent] = []
        self._lock = Lock()

    def record(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)
            if self.path is not None:
                data = asdict(event)
                data["timestamp"] = event.timestamp.isoformat()
                try:
                    with self.path.open("a", encoding="utf-8") as output:
                        output.write(json.dumps(data, ensure_ascii=False) + "\n")
                except OSError as error:
                    self.file_error = error

    def filter(
        self,
        *,
        level: AuditLevel | None = None,
        action: str | None = None,
        client_id: str | None = None,
        transaction_id: str | None = None,
        since: datetime | None = None,
    ) -> list[AuditEvent]:
        with self._lock:
            return [
                event
                for event in self._events
                if (level is None or event.level == level)
                and (action is None or event.action == action)
                and (client_id is None or client_id in (event.sender_id, event.recipient_id))
                and (transaction_id is None or event.transaction_id == transaction_id)
                and (since is None or event.timestamp >= since)
            ]

    def suspicious_operations(self) -> list[AuditEvent]:
        return [
            event for event in self.filter(action="risk_assessed")
            if event.risk in ("medium", "high")
        ]

    def client_risk_profile(self, client_id: str) -> dict[str, int]:
        counts = dict.fromkeys(("low", "medium", "high"), 0)
        rank = {level: index for index, level in enumerate(counts)}
        highest: dict[str, str] = {}
        for event in self.filter(action="risk_assessed", client_id=client_id):
            if event.sender_id != client_id or event.risk not in rank:
                continue
            previous = highest.get(event.transaction_id, "low")
            if rank[event.risk] >= rank[previous]:
                highest[event.transaction_id] = event.risk
        for risk in highest.values():
            counts[risk] += 1
        return counts

    def error_statistics(self) -> dict[str, int]:
        return dict(Counter(event.error for event in self.filter() if event.error is not None))

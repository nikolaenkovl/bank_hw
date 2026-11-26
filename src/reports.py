from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Union

from src.audit import AuditEvent
from src.bank import Bank


ReportRow = dict[str, Union[str, int]]


@dataclass
class Report:
    title: str
    rows: list[ReportRow]


class ReportBuilder:
    def __init__(self, bank: Bank) -> None:
        self._bank = bank
        self._balance_history: dict[datetime, dict[str, Decimal]] = {}

    @staticmethod
    def _event_row(event: AuditEvent, section: str) -> ReportRow:
        return {
            "section": section,
            "timestamp": event.timestamp.isoformat(),
            "transaction_id": event.transaction_id,
            "action": event.action,
            "amount": event.amount,
            "currency": event.currency,
            "risk": event.risk or "",
            "reasons": ", ".join(event.reasons),
            "error": event.error or "",
            "detail": event.detail or "",
        }

    @staticmethod
    def _transaction_states(events: list[AuditEvent]) -> dict[str, AuditEvent]:
        return {
            event.transaction_id: event
            for event in events
            if event.action != "risk_assessed"
        }

    def client_report(self, client_id: str) -> Report:
        client = self._bank.get_client(client_id)
        rows: list[ReportRow] = [{
            "section": "client",
            "client_id": client_id,
            "name": client.full_name,
            "status": client.status.value,
        }]
        for account in self._bank.search_accounts(client_id=client_id):
            rows.append({
                "section": "account",
                "account_type": type(account).__name__,
                "account_number": f"****{account.account_number[-4:]}",
                "status": account.status.value,
                "available_balance": str(account.balance),
                "total_balance": str(account.total_balance),
                "currency": account.currency,
            })
        events = self._bank.audit_log.filter(client_id=client_id)
        rows.extend(self._event_row(event, "transaction") for event in events)
        rows.extend(
            {"section": "risk_profile", "risk": risk, "count": count}
            for risk, count in self._bank.audit_log.client_risk_profile(client_id).items()
        )
        return Report(f"Отчёт по клиенту — {client.full_name}", rows)

    def bank_report(self) -> Report:
        rows: list[ReportRow] = [
            {"section": "balance", "currency": currency, "total_balance": str(total)}
            for currency, total in self._bank.get_total_balance().items()
        ]
        for currency, ranking in self._bank.get_clients_ranking().items():
            rows.extend(
                {
                    "section": "ranking", "rank": rank, "client_id": client.client_id,
                    "name": client.full_name, "currency": currency, "total_balance": str(total),
                }
                for rank, (client, total) in enumerate(ranking, start=1)
            )
        states = self._transaction_states(self._bank.audit_log.filter())
        rows.extend(
            {"section": "transaction_status", "action": action, "count": count}
            for action, count in sorted(Counter(event.action for event in states.values()).items())
        )
        return Report("Отчёт по банку", rows)

    def risk_report(self) -> Report:
        audit = self._bank.audit_log
        rows = [
            {**self._event_row(event, "suspicious_operation"), "sender_id": event.sender_id}
            for event in audit.suspicious_operations()
        ]
        rows.extend(
            {"section": "error_count", "error": error, "count": count}
            for error, count in sorted(audit.error_statistics().items())
        )
        return Report("Отчёт по рискам", rows)

    def capture_balances(self, timestamp: datetime) -> None:
        self._balance_history[timestamp] = self._bank.get_total_balance()

    @staticmethod
    def format_text(report: Report) -> str:
        lines = [report.title]
        for row in report.rows:
            lines.append(" | ".join(f"{key}={value}" for key, value in row.items() if value != ""))
        return "\n".join(lines) + "\n"

    @staticmethod
    def export_to_json(report: Report, path: str | Path) -> None:
        data = {"title": report.title, "rows": report.rows}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def export_to_csv(report: Report, path: str | Path) -> None:
        fields = list(dict.fromkeys(["section"] + [key for row in report.rows for key in row]))
        with Path(path).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(report.rows)

    def save_charts(self, directory: str | Path) -> list[Path]:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
        from matplotlib.figure import Figure

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        events = self._bank.audit_log.filter()
        risks = Counter(event.risk for event in events if event.action == "risk_assessed")
        states = Counter(event.action for event in self._transaction_states(events).values())
        history = sorted(self._balance_history.items())
        currencies = sorted({currency for _, totals in history for currency in totals})

        pie = Figure(figsize=(6, 4), constrained_layout=True)
        axis = pie.subplots()
        axis.set_title("Распределение оценок риска")
        if risks:
            labels = {"low": "Низкий", "medium": "Средний", "high": "Высокий"}
            levels = [level for level in labels if risks[level]]
            axis.pie([risks[level] for level in levels],
                     labels=[labels[level] for level in levels], autopct="%1.0f%%")
        else:
            axis.text(0.5, 0.5, "Нет оценок риска", ha="center", va="center")
            axis.set_axis_off()

        bars = Figure(figsize=(7, 4), constrained_layout=True)
        axis = bars.subplots()
        axis.set_title("Транзакции по итоговому статусу")
        labels = {
            "queued": "В очереди", "retry_scheduled": "На повторе", "completed": "Исполнены",
            "rejected": "Отклонены", "cancelled": "Отменены",
        }
        axis.bar(list(labels.values()), [states[state] for state in labels])
        axis.set_ylabel("Количество")

        movement = Figure(figsize=(8, 3 * max(1, len(currencies))), constrained_layout=True)
        axes = movement.subplots(max(1, len(currencies)), 1, squeeze=False, sharex=True)
        movement.suptitle("Движение общего баланса")
        for axis, currency in zip(axes[:, 0], currencies):
            axis.plot(
                [timestamp for timestamp, _ in history],
                [float(totals.get(currency, Decimal(0))) for _, totals in history],
                marker="o",
            )
            axis.set_ylabel(currency)
            axis.grid(alpha=0.3)
        if not currencies:
            axes[0, 0].text(0.5, 0.5, "Нет снимков баланса", ha="center", va="center")
            axes[0, 0].set_axis_off()
        else:
            locator = AutoDateLocator()
            axes[-1, 0].xaxis.set_major_locator(locator)
            axes[-1, 0].xaxis.set_major_formatter(ConciseDateFormatter(locator))

        paths = []
        for name, figure in (("risk", pie), ("transactions", bars), ("balance_history", movement)):
            path = directory / f"{name}.png"
            FigureCanvasAgg(figure).print_png(path)
            paths.append(path)
        return paths

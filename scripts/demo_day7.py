from argparse import ArgumentParser
from datetime import datetime, timedelta
from pathlib import Path

from src.bank import Bank, Client
from src.reports import ReportBuilder
from src.transactions import Transaction, TransactionType


def run(output: Path) -> None:
    now = datetime(2025, 1, 1, 12)
    bank = Bank(clock=lambda: now)
    anna_id = bank.add_client(
        Client("Анна Иванова", 28, {"email": "anna@example.com"}), "demo-password"
    )
    ivan_id = bank.add_client(
        Client("Иван Петров", 35, {"email": "ivan@example.com"}), "demo-password"
    )
    sender = bank.open_account(anna_id, balance=200_000)
    recipient = bank.open_account(ivan_id, balance=500, currency="USD")
    processor = bank.create_transaction_processor(exchange_rates={("RUB", "USD"): "0.01"})
    builder = ReportBuilder(bank)
    builder.capture_balances(now)

    for amount in (2_000, 3_000, 100_000):
        now += timedelta(days=1)
        processor.queue.add(Transaction(
            sender, recipient, amount, "RUB", TransactionType.EXTERNAL, created_at=now
        ))
        processor.process_ready()
        builder.capture_balances(now)

    output.mkdir(parents=True, exist_ok=True)
    reports = {
        "client": builder.client_report(anna_id),
        "bank": builder.bank_report(),
        "risk": builder.risk_report(),
    }
    for name, report in reports.items():
        text = builder.format_text(report)
        (output / f"{name}.txt").write_text(text, encoding="utf-8")
        builder.export_to_json(report, output / f"{name}.json")
        builder.export_to_csv(report, output / f"{name}.csv")
        print(f"{report.title}: {len(report.rows)} строк")
    for path in builder.save_charts(output):
        print(path)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports"), help="Каталог отчётов и графиков")
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()

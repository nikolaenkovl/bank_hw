from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from src.audit import AuditLog
from src.bank import Bank, Client
from src.transactions import Transaction


def main() -> None:
    now = datetime(2025, 1, 1, 12)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "audit.jsonl"
        audit = AuditLog(path)
        bank = Bank(clock=lambda: now, audit_log=audit)
        sender_id = bank.add_client(
            Client("Анна Иванова", 28, {"email": "anna@example.com"}), "demo-password"
        )
        recipient_id = bank.add_client(
            Client("Иван Петров", 35, {"email": "ivan@example.com"}), "demo-password"
        )
        sender = bank.open_account(sender_id, balance=200_000)
        recipient = bank.open_account(recipient_id)
        processor = bank.create_transaction_processor()
        for amount in (200, 100, 100_000):
            processor.queue.add(Transaction(sender, recipient, amount, "RUB", created_at=now))
            transaction, = processor.process_ready()
            print(amount, transaction.status.value, transaction.risk.level.value)
        print("Подозрительные операции:", [event.reasons for event in audit.suspicious_operations()])
        print("Профиль отправителя:", audit.client_risk_profile(sender_id))
        print("Ошибки:", audit.error_statistics())
        print("Записей в файле:", len(path.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    main()

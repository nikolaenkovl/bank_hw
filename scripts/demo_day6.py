from argparse import ArgumentParser
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from src.audit import AuditLog
from src.bank import Bank, Client
from src.bank_account import InvestmentAccount, PremiumAccount, SavingsAccount
from src.transactions import Transaction, TransactionType


def run(audit_path: Path) -> None:
    now = datetime(2025, 1, 1, 5)
    audit = AuditLog(audit_path)
    bank = Bank(clock=lambda: now, audit_log=audit)
    names = (
        "Анна Иванова", "Иван Петров", "Елена Смирнова",
        "Олег Соколов", "Мария Кузнецова", "Павел Орлов",
    )
    clients = [
        Client(name, 25 + index, {"email": f"client{index}@example.com"})
        for index, name in enumerate(names, start=1)
    ]
    accounts = []
    dollars = []
    account_types = (SavingsAccount, PremiumAccount, InvestmentAccount)
    for index, client in enumerate(clients):
        client_id = bank.add_client(client, "demo-password")
        account_type = account_types[index % len(account_types)]
        accounts.append(bank.open_account(client_id, account_type, balance=15_000 + 1_000 * index))
        dollars.append(bank.open_account(client_id, balance=500, currency="USD"))
    print("Вход клиента:", bank.authenticate_client(clients[0].client_id, "demo-password"))
    bank.freeze_account(accounts[-1].account_number)
    accounts[2].invest("bonds", 500)
    processor = bank.create_transaction_processor(exchange_rates={("RUB", "USD"): "0.01"})
    transactions = []

    def submit(sender, recipient, amount, kind=TransactionType.INTERNAL, **options):
        transaction = Transaction(sender, recipient, amount, sender.currency, kind, created_at=now)
        processor.queue.add(transaction, **options)
        transactions.append(transaction)
        return transaction

    now = now.replace(hour=4, minute=30)
    submit(accounts[0], accounts[1], 200)
    processor.process_ready()
    now = now.replace(hour=12, minute=0)

    for round_number in range(4):
        for index, sender in enumerate(accounts[:-1]):
            recipient = accounts[(index + 1) % 5]
            submit(sender, recipient, 250 + 50 * round_number)
            if index == 0:
                submit(sender, dollars[1], 300, TransactionType.EXTERNAL)
        processor.process_ready()
        now += timedelta(minutes=15)

    for recipient in (accounts[1], accounts[1], accounts[1], accounts[4]):
        submit(accounts[0], recipient, 100)
    processor.process_ready()
    now += timedelta(minutes=15)

    submit(accounts[1], accounts[2], 150_000, priority=10)
    submit(accounts[2], accounts[-1], 500)
    submit(accounts[3], accounts[2], 75_000)
    submit(dollars[0], accounts[2], 20)
    submit(accounts[4], accounts[4], 100)
    cancelled = submit(accounts[2], accounts[1], 100)
    processor.queue.cancel(cancelled.transaction_id)
    submit(accounts[0], accounts[1], 50, scheduled_at=now + timedelta(minutes=15))
    processor.process_ready()
    now += timedelta(minutes=15)
    processor.process_ready()

    if audit.file_error is not None:
        raise audit.file_error

    labels = {tx.transaction_id: index for index, tx in enumerate(transactions, start=1)}
    print(f"Клиентов: {len(clients)}, счетов: {len(bank.search_accounts())}, переводов: {len(transactions)}")
    print("Журнал очереди и исполнения")
    for event in audit.filter():
        if event.action != "risk_assessed":
            print(labels[event.transaction_id], event.action, event.detail or "")

    client = clients[0]
    print(f"Счета клиента {client.full_name}")
    for account in bank.search_accounts(client_id=client.client_id):
        print(account)
    print("История клиента")
    client_transactions = {
        event.transaction_id for event in audit.filter(client_id=client.client_id, action="queued")
    }
    for tx in transactions:
        if tx.transaction_id in client_transactions:
            print(labels[tx.transaction_id], tx.amount, tx.currency, tx.status.value)

    print("Подозрительные операции")
    for event in audit.suspicious_operations():
        print(labels[event.transaction_id], event.risk, ", ".join(event.reasons))
    print("Риск-профиль клиента", audit.client_risk_profile(client.client_id))
    print("Топ-3 клиентов по валютам")
    for currency, ranking in bank.get_clients_ranking().items():
        print(currency, [(owner.full_name, balance) for owner, balance in ranking[:3]])
    print("Статистика транзакций", dict(Counter(tx.status.value for tx in transactions)))
    print("Статистика ошибок", audit.error_statistics())
    print("Общий баланс по валютам", bank.get_total_balance())
    print("Событий записано в JSONL", len(audit.filter()))


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--audit-file", type=Path, help="Куда дописывать события аудита в JSONL")
    args = parser.parse_args()
    if args.audit_file is not None:
        run(args.audit_file)
    else:
        with TemporaryDirectory() as directory:
            run(Path(directory) / "audit.jsonl")


if __name__ == "__main__":
    main()

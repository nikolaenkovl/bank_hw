from datetime import datetime, timedelta

from src.bank import Bank, Client
from src.bank_account import BankAccount, PremiumAccount, SavingsAccount
from src.transactions import Transaction, TransactionProcessor, TransactionQueue, TransactionType


def main() -> None:
    now = datetime(2025, 1, 1, 5)
    bank = Bank(clock=lambda: now)
    client_id = bank.add_client(
        Client("Анна Иванова", 28, {"email": "anna@example.com"}), "demo-password"
    )
    guarded = bank.open_account(client_id, balance=500)
    now = now.replace(hour=4, minute=30)
    queue = TransactionQueue(clock=lambda: now)
    processor = TransactionProcessor(queue, exchange_rates={("RUB", "USD"): "0.01"})

    sender = BankAccount("Иван", 500)
    recipient = BankAccount("Ольга")
    usd = BankAccount("Елена", currency="USD")
    premium = PremiumAccount("Олег", 20, overdraft_limit=100, withdrawal_fee=5)
    savings = SavingsAccount("Мария", 120, min_balance=100)
    frozen = BankAccount("Павел", status="frozen")
    specs = [
        (sender, recipient, 50),
        (sender, usd, 100, TransactionType.EXTERNAL),
        (premium, recipient, 70),
        (sender, frozen, 10),
        (savings, recipient, 30),
        (sender, recipient, 25),
        (sender, recipient, 30),
        (guarded, recipient, 40),
        (sender, recipient, 20),
        (recipient, sender, 10),
    ]
    transactions = [
        Transaction(payer, payee, amount, payer.currency, *kind, created_at=now)
        for payer, payee, amount, *kind in specs
    ]
    for index, transaction in enumerate(transactions):
        queue.add(
            transaction,
            priority=5 if index == 1 else 0,
            scheduled_at=now + timedelta(minutes=30) if index == 6 else None,
        )
    queue.cancel(transactions[5].transaction_id)

    for transaction in processor.process_ready():
        print(f"{transactions.index(transaction) + 1}: {transaction.status.value}")
    now += timedelta(hours=1)
    processor.process_ready()

    print("Итог по десяти транзакциям")
    for index, transaction in enumerate(transactions, start=1):
        detail = transaction.failure_reason or f"комиссия {transaction.fee} {transaction.currency}"
        print(f"{index}: {transaction.status.value}, попыток {transaction.attempts}, {detail}")


if __name__ == "__main__":
    main()

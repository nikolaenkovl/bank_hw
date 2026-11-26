from datetime import datetime

from src.bank import Bank, Client, NightOperationError
from src.bank_account import AccountFrozenError, InvestmentAccount


def main() -> None:
    current_time = datetime(2025, 1, 1, 12)
    bank = Bank(clock=lambda: current_time)
    anna = Client("Анна Иванова", 28, {"email": "anna@example.com"})
    ivan = Client("Иван Петров", 35, {"email": "ivan@example.com"})
    anna_id = bank.add_client(anna, "anna-demo-password")
    ivan_id = bank.add_client(ivan, "ivan-demo-password")

    savings = bank.open_account(anna_id, balance=1_000)
    investment = bank.open_account(ivan_id, InvestmentAccount, balance=600)
    investment.invest("bonds", 300)
    print("Успешный вход:", bank.authenticate_client(anna_id, "anna-demo-password"))

    bank.freeze_account(savings.account_number)
    try:
        savings.withdraw(100)
    except AccountFrozenError as error:
        print(error)
    print("Замороженные счета:", [str(account) for account in bank.search_accounts(status="frozen")])
    bank.unfreeze_account(savings.account_number)
    savings.withdraw(100)
    empty = bank.open_account(anna_id)
    bank.close_account(empty.account_number)

    for _ in range(3):
        print("Вход с неверным паролем:", bank.authenticate_client(ivan_id, "wrong"))
    print("Статус Ивана:", ivan.status.value)

    current_time = current_time.replace(hour=2)
    try:
        savings.deposit(50)
    except NightOperationError as error:
        print(error)

    print("Общие балансы:", bank.get_total_balance())
    for currency, ranking in bank.get_clients_ranking().items():
        print(currency, [(client.full_name, balance) for client, balance in ranking])
    print("Подозрительные действия:", [event.reason for event in bank.suspicious_activities])


if __name__ == "__main__":
    main()

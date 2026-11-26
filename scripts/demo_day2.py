from src.bank_account import InvestmentAccount, PremiumAccount, SavingsAccount


def main() -> None:
    savings = [
        SavingsAccount("Анна", 1_000, min_balance=200, monthly_interest_rate="0.02"),
        SavingsAccount("Иван", 500, min_balance=100),
    ]
    premium = [
        PremiumAccount("Мария", 100, overdraft_limit=200, withdrawal_fee=10),
        PremiumAccount("Олег", 1_000, withdrawal_limit=500, withdrawal_fee=20),
    ]
    investments = [
        InvestmentAccount("Елена", 1_000),
        InvestmentAccount("Павел", 800),
    ]
    growth_rates = {"stocks": "0.10", "bonds": "0.04", "etf": "0.07"}

    for account in savings:
        print("Monthly interest:", account.apply_monthly_interest())

    for account in investments:
        for asset_type, amount in (("stocks", 200), ("bonds", 100), ("etf", 300)):
            account.invest(asset_type, amount)
        print("Projected yearly growth:", account.project_yearly_growth(growth_rates))

    for account in [*savings, *premium, *investments]:
        account.withdraw(150)
        print(account)
        print(account.get_account_info())


if __name__ == "__main__":
    main()

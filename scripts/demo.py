from src.bank_account import AccountFrozenError, AccountStatus, BankAccount


def main() -> None:
    active = BankAccount("Анна", balance="1000.00")
    frozen = BankAccount("Иван", balance="500.00", currency="USD", status=AccountStatus.FROZEN)
    print(active)
    print(frozen)

    for operation in (frozen.deposit, frozen.withdraw):
        try:
            operation("100.00")
        except AccountFrozenError as error:
            print(f"{operation.__name__}: {error}")

    active.deposit("250.50")
    active.withdraw("100.25")
    print(active)


if __name__ == "__main__":
    main()

"""TDD: BankAccount — tests first, then implementation."""

import unittest
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


# ---------------------------------------------------------------------------
# Tests (written FIRST — these define the contract)
# ---------------------------------------------------------------------------

class TestBankAccountDeposit(unittest.TestCase):
    def test_deposit_positive_amount(self):
        acc = BankAccount("Alice", 100)
        acc.deposit(50)
        self.assertEqual(acc.get_balance(), 150)

    def test_deposit_zero_raises(self):
        acc = BankAccount("Alice", 100)
        with self.assertRaises(ValueError):
            acc.deposit(0)

    def test_deposit_negative_raises(self):
        acc = BankAccount("Alice", 100)
        with self.assertRaises(ValueError):
            acc.deposit(-10)

    def test_deposit_returns_new_balance(self):
        acc = BankAccount("Alice", 0)
        result = acc.deposit(75)
        self.assertEqual(result, 75)


class TestBankAccountWithdraw(unittest.TestCase):
    def test_withdraw_valid_amount(self):
        acc = BankAccount("Bob", 200)
        acc.withdraw(50)
        self.assertEqual(acc.get_balance(), 150)

    def test_withdraw_exact_balance(self):
        acc = BankAccount("Bob", 100)
        acc.withdraw(100)
        self.assertEqual(acc.get_balance(), 0)

    def test_withdraw_overdraft_raises(self):
        acc = BankAccount("Bob", 50)
        with self.assertRaises(InsufficientFundsError):
            acc.withdraw(100)

    def test_withdraw_zero_raises(self):
        acc = BankAccount("Bob", 100)
        with self.assertRaises(ValueError):
            acc.withdraw(0)

    def test_withdraw_negative_raises(self):
        acc = BankAccount("Bob", 100)
        with self.assertRaises(ValueError):
            acc.withdraw(-20)

    def test_withdraw_returns_new_balance(self):
        acc = BankAccount("Bob", 200)
        result = acc.withdraw(30)
        self.assertEqual(result, 170)

    def test_balance_unchanged_after_failed_withdraw(self):
        acc = BankAccount("Bob", 50)
        with self.assertRaises(InsufficientFundsError):
            acc.withdraw(999)
        self.assertEqual(acc.get_balance(), 50)


class TestBankAccountTransfer(unittest.TestCase):
    def test_transfer_moves_funds(self):
        src = BankAccount("Alice", 300)
        dst = BankAccount("Bob", 100)
        src.transfer(dst, 200)
        self.assertEqual(src.get_balance(), 100)
        self.assertEqual(dst.get_balance(), 300)

    def test_transfer_overdraft_raises(self):
        src = BankAccount("Alice", 50)
        dst = BankAccount("Bob", 100)
        with self.assertRaises(InsufficientFundsError):
            src.transfer(dst, 100)
        # Both balances unchanged
        self.assertEqual(src.get_balance(), 50)
        self.assertEqual(dst.get_balance(), 100)

    def test_transfer_negative_raises(self):
        src = BankAccount("Alice", 100)
        dst = BankAccount("Bob", 100)
        with self.assertRaises(ValueError):
            src.transfer(dst, -10)

    def test_transfer_zero_raises(self):
        src = BankAccount("Alice", 100)
        dst = BankAccount("Bob", 100)
        with self.assertRaises(ValueError):
            src.transfer(dst, 0)

    def test_transfer_to_self_raises(self):
        acc = BankAccount("Alice", 100)
        with self.assertRaises(ValueError):
            acc.transfer(acc, 50)


class TestBankAccountGetBalance(unittest.TestCase):
    def test_initial_balance(self):
        acc = BankAccount("Eve", 500)
        self.assertEqual(acc.get_balance(), 500)

    def test_default_balance_is_zero(self):
        acc = BankAccount("Eve")
        self.assertEqual(acc.get_balance(), 0)

    def test_negative_initial_balance_raises(self):
        with self.assertRaises(ValueError):
            BankAccount("Eve", -100)


class TestBankAccountConcurrency(unittest.TestCase):
    def test_concurrent_deposits(self):
        acc = BankAccount("Shared", 0)
        num_threads = 100
        deposit_amount = 10

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(acc.deposit, deposit_amount) for _ in range(num_threads)]
            for f in as_completed(futures):
                f.result()

        self.assertEqual(acc.get_balance(), num_threads * deposit_amount)

    def test_concurrent_withdrawals_no_overdraft(self):
        acc = BankAccount("Shared", 1000)
        num_threads = 100
        withdraw_amount = 10
        successes = []
        failures = []

        def try_withdraw():
            try:
                acc.withdraw(withdraw_amount)
                return True
            except InsufficientFundsError:
                return False

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(try_withdraw) for _ in range(num_threads)]
            for f in as_completed(futures):
                if f.result():
                    successes.append(1)
                else:
                    failures.append(1)

        self.assertEqual(acc.get_balance(), 1000 - len(successes) * withdraw_amount)
        self.assertGreaterEqual(acc.get_balance(), 0)

    def test_concurrent_transfers_conserve_total(self):
        a = BankAccount("A", 5000)
        b = BankAccount("B", 5000)
        total_before = a.get_balance() + b.get_balance()

        def transfer_back_and_forth():
            for _ in range(50):
                try:
                    a.transfer(b, 1)
                except InsufficientFundsError:
                    pass
                try:
                    b.transfer(a, 1)
                except InsufficientFundsError:
                    pass

        threads = [threading.Thread(target=transfer_back_and_forth) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total_after = a.get_balance() + b.get_balance()
        self.assertEqual(total_before, total_after)
        self.assertGreaterEqual(a.get_balance(), 0)
        self.assertGreaterEqual(b.get_balance(), 0)


# ---------------------------------------------------------------------------
# Implementation (written SECOND — make the tests pass)
# ---------------------------------------------------------------------------

class InsufficientFundsError(Exception):
    """Raised when a withdrawal or transfer exceeds available balance."""


class BankAccount:
    _lock_order_counter = 0
    _lock_order_lock = threading.Lock()

    def __init__(self, owner: str, balance: float = 0):
        if balance < 0:
            raise ValueError("Initial balance cannot be negative")
        self.owner = owner
        self._balance = balance
        self._lock = threading.Lock()
        with BankAccount._lock_order_lock:
            self._order = BankAccount._lock_order_counter
            BankAccount._lock_order_counter += 1

    def get_balance(self) -> float:
        with self._lock:
            return self._balance

    def deposit(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        with self._lock:
            self._balance += amount
            return self._balance

    def withdraw(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        with self._lock:
            if amount > self._balance:
                raise InsufficientFundsError(
                    f"Cannot withdraw {amount}: only {self._balance} available"
                )
            self._balance -= amount
            return self._balance

    def transfer(self, target: "BankAccount", amount: float) -> None:
        if amount <= 0:
            raise ValueError("Transfer amount must be positive")
        if target is self:
            raise ValueError("Cannot transfer to the same account")

        # Acquire locks in a consistent order (by _order) to prevent deadlock
        first, second = (self, target) if self._order < target._order else (target, self)
        with first._lock:
            with second._lock:
                if amount > self._balance:
                    raise InsufficientFundsError(
                        f"Cannot transfer {amount}: only {self._balance} available"
                    )
                self._balance -= amount
                target._balance += amount


# ---------------------------------------------------------------------------
# __main__ — quick smoke-test assertions + full unittest suite
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Smoke tests
    a = BankAccount("Alice", 1000)
    b = BankAccount("Bob", 500)

    assert a.get_balance() == 1000
    assert b.get_balance() == 500

    a.deposit(200)
    assert a.get_balance() == 1200

    a.withdraw(100)
    assert a.get_balance() == 1100

    a.transfer(b, 300)
    assert a.get_balance() == 800
    assert b.get_balance() == 800

    try:
        a.withdraw(10000)
        assert False, "Should have raised InsufficientFundsError"
    except InsufficientFundsError:
        pass

    try:
        a.deposit(-1)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    try:
        a.transfer(a, 10)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    print("All smoke-test assertions passed.\n")

    # Full test suite
    unittest.main(verbosity=2)

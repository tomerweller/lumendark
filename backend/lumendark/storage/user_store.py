from decimal import Decimal
from threading import RLock
from typing import Optional

from lumendark.models.user import User, UserBalance


class UserStore:
    """
    Thread-safe in-memory storage for user balances.

    Tracks available and liability balances for each user.
    """

    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._lock = RLock()

    def get(self, address: str) -> Optional[User]:
        """Get a user by address, or None if not found."""
        with self._lock:
            return self._users.get(address)

    def get_or_create(self, address: str) -> User:
        """Get a user by address, creating if not found."""
        with self._lock:
            if address not in self._users:
                self._users[address] = User(address=address)
            return self._users[address]

    def deposit(self, address: str, asset: str, amount: Decimal) -> None:
        """
        Process a deposit: increase user's available balance.
        Creates user if this is their first deposit.
        """
        with self._lock:
            user = self.get_or_create(address)
            user.get_balance(asset).deposit(amount)

    def can_allocate(self, address: str, asset: str, amount: Decimal) -> bool:
        """Check if user can allocate amount from available to liabilities."""
        with self._lock:
            user = self.get(address)
            if user is None:
                return False
            return user.get_balance(asset).can_allocate(amount)

    def allocate(self, address: str, asset: str, amount: Decimal) -> None:
        """
        Allocate funds for an order: move from available to liabilities.
        Raises ValueError if insufficient balance.
        """
        with self._lock:
            user = self.get(address)
            if user is None:
                raise ValueError(f"User not found: {address}")
            user.get_balance(asset).allocate(amount)

    def release(self, address: str, asset: str, amount: Decimal) -> None:
        """
        Release funds from a cancelled order: move from liabilities to available.
        """
        with self._lock:
            user = self.get(address)
            if user is None:
                raise ValueError(f"User not found: {address}")
            user.get_balance(asset).release(amount)

    def consume_liability(self, address: str, asset: str, amount: Decimal) -> None:
        """
        Consume liability for a filled order (reduce liabilities without
        returning to available - the funds are transferred in the trade).
        """
        with self._lock:
            user = self.get(address)
            if user is None:
                raise ValueError(f"User not found: {address}")
            user.get_balance(asset).consume_liability(amount)

    def credit(self, address: str, asset: str, amount: Decimal) -> None:
        """
        Credit funds to a user's available balance (e.g., from a trade).
        """
        with self._lock:
            user = self.get_or_create(address)
            user.get_balance(asset).available += amount

    def can_withdraw(self, address: str, asset: str, amount: Decimal) -> bool:
        """Check if user can withdraw the specified amount."""
        with self._lock:
            user = self.get(address)
            if user is None:
                return False
            return user.get_balance(asset).can_withdraw(amount)

    def withdraw(self, address: str, asset: str, amount: Decimal) -> None:
        """
        Process a withdrawal: decrease user's available balance.
        Raises ValueError if insufficient balance.
        """
        with self._lock:
            user = self.get(address)
            if user is None:
                raise ValueError(f"User not found: {address}")
            user.get_balance(asset).withdraw(amount)

    def get_available(self, address: str, asset: str) -> Decimal:
        """Get user's available balance for an asset."""
        with self._lock:
            user = self.get(address)
            if user is None:
                return Decimal("0")
            return user.get_balance(asset).available

    def get_liabilities(self, address: str, asset: str) -> Decimal:
        """Get user's liabilities for an asset."""
        with self._lock:
            user = self.get(address)
            if user is None:
                return Decimal("0")
            return user.get_balance(asset).liabilities

    def get_total(self, address: str, asset: str) -> Decimal:
        """Get user's total balance (available + liabilities) for an asset."""
        with self._lock:
            user = self.get(address)
            if user is None:
                return Decimal("0")
            return user.get_balance(asset).total

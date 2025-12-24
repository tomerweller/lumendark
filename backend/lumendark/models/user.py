from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class UserBalance:
    """
    Balance tracking for a single asset.

    - available: Funds that can be used for new orders or withdrawals
    - liabilities: Funds locked in open orders
    - total = available + liabilities (should match on-chain balance)
    """

    available: Decimal = Decimal("0")
    liabilities: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        """Total balance including funds locked in orders."""
        return self.available + self.liabilities

    def can_allocate(self, amount: Decimal) -> bool:
        """Check if we can allocate this amount from available to liabilities."""
        return self.available >= amount

    def allocate(self, amount: Decimal) -> None:
        """Move funds from available to liabilities (for new orders)."""
        if not self.can_allocate(amount):
            raise ValueError(f"Insufficient available balance: have {self.available}, need {amount}")
        self.available -= amount
        self.liabilities += amount

    def release(self, amount: Decimal) -> None:
        """Move funds from liabilities back to available (for cancellations)."""
        if self.liabilities < amount:
            raise ValueError(f"Insufficient liabilities: have {self.liabilities}, need {amount}")
        self.liabilities -= amount
        self.available += amount

    def consume_liability(self, amount: Decimal) -> None:
        """Remove from liabilities without returning to available (for fills)."""
        if self.liabilities < amount:
            raise ValueError(f"Insufficient liabilities: have {self.liabilities}, need {amount}")
        self.liabilities -= amount

    def deposit(self, amount: Decimal) -> None:
        """Add funds to available balance."""
        self.available += amount

    def can_withdraw(self, amount: Decimal) -> bool:
        """Check if we can withdraw this amount."""
        return self.available >= amount

    def withdraw(self, amount: Decimal) -> None:
        """Remove funds from available balance."""
        if not self.can_withdraw(amount):
            raise ValueError(f"Insufficient available balance: have {self.available}, need {amount}")
        self.available -= amount


@dataclass
class User:
    """
    User account with balances for both assets.
    """

    address: str
    balance_a: UserBalance = field(default_factory=UserBalance)
    balance_b: UserBalance = field(default_factory=UserBalance)

    def get_balance(self, asset: str) -> UserBalance:
        """Get balance for the specified asset ('a' or 'b')."""
        if asset == "a":
            return self.balance_a
        elif asset == "b":
            return self.balance_b
        else:
            raise ValueError(f"Invalid asset: {asset}")

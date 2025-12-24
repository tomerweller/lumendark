from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
import uuid


class OrderSide(Enum):
    """Order side: BUY or SELL."""

    BUY = "buy"  # Buying asset A, selling asset B
    SELL = "sell"  # Selling asset A, buying asset B


class OrderStatus(Enum):
    """Order lifecycle status."""

    OPEN = "open"  # Active in order book
    PARTIALLY_FILLED = "partially_filled"  # Some quantity executed
    FILLED = "filled"  # Completely executed
    CANCELLED = "cancelled"  # Cancelled by user


@dataclass
class Order:
    """
    Represents a limit order in the order book.

    Price is in asset B per unit of asset A.
    Quantity is in asset A.
    """

    id: str
    user_address: str
    side: OrderSide
    price: Decimal  # Price in asset B per unit of asset A
    quantity: Decimal  # Quantity of asset A
    filled_quantity: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.OPEN
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def create(
        user_address: str,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> "Order":
        """Factory method to create a new order with generated ID."""
        return Order(
            id=str(uuid.uuid4()),
            user_address=user_address,
            side=side,
            price=price,
            quantity=quantity,
        )

    @property
    def remaining_quantity(self) -> Decimal:
        """Quantity still to be filled."""
        return self.quantity - self.filled_quantity

    @property
    def is_active(self) -> bool:
        """Whether this order can still be matched."""
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    @property
    def liability_amount(self) -> Decimal:
        """
        Amount locked as liability for this order.
        - BUY orders lock asset B (price * remaining_quantity)
        - SELL orders lock asset A (remaining_quantity)
        """
        if self.side == OrderSide.BUY:
            return self.price * self.remaining_quantity
        else:
            return self.remaining_quantity

    @property
    def liability_asset(self) -> str:
        """Which asset is locked for this order's liability."""
        return "b" if self.side == OrderSide.BUY else "a"

    def fill(self, quantity: Decimal) -> None:
        """Record a fill of the given quantity."""
        self.filled_quantity += quantity
        if self.remaining_quantity == Decimal("0"):
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    def cancel(self) -> None:
        """Mark the order as cancelled."""
        self.status = OrderStatus.CANCELLED

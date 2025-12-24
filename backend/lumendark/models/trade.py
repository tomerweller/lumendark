from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import uuid


@dataclass
class Trade:
    """
    Represents an executed trade between two orders.

    A trade occurs when a buy order matches a sell order.
    - buyer_address receives `quantity` of asset A
    - seller_address receives `quantity * price` of asset B
    """

    id: str
    buyer_address: str  # Address receiving asset A
    seller_address: str  # Address receiving asset B
    buy_order_id: str  # The buy order involved
    sell_order_id: str  # The sell order involved
    price: Decimal  # Execution price (in asset B per unit of asset A)
    quantity: Decimal  # Quantity of asset A traded
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def create(
        buyer_address: str,
        seller_address: str,
        buy_order_id: str,
        sell_order_id: str,
        price: Decimal,
        quantity: Decimal,
    ) -> "Trade":
        """Factory method to create a new trade with generated ID."""
        return Trade(
            id=str(uuid.uuid4()),
            buyer_address=buyer_address,
            seller_address=seller_address,
            buy_order_id=buy_order_id,
            sell_order_id=sell_order_id,
            price=price,
            quantity=quantity,
        )

    @property
    def value(self) -> Decimal:
        """Value of the trade in asset B."""
        return self.price * self.quantity

    @property
    def amount_a(self) -> Decimal:
        """Amount of asset A transferred (seller -> buyer)."""
        return self.quantity

    @property
    def amount_b(self) -> Decimal:
        """Amount of asset B transferred (buyer -> seller)."""
        return self.value

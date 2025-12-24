from decimal import Decimal
from threading import RLock
from typing import Iterator, Optional

from sortedcontainers import SortedList

from lumendark.models.order import Order, OrderSide


class OrderBook:
    """
    Price-time priority order book.

    - Bids (buy orders): sorted by price descending, then time ascending
    - Asks (sell orders): sorted by price ascending, then time ascending

    Best bid = highest price buyer
    Best ask = lowest price seller
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._orders: dict[str, Order] = {}  # order_id -> Order

        # Bids: highest price first, earliest time first at same price
        # Key: (-price, created_at, order_id) for descending price sort
        self._bids: SortedList[Order] = SortedList(
            key=lambda o: (-o.price, o.created_at, o.id)
        )

        # Asks: lowest price first, earliest time first at same price
        # Key: (price, created_at, order_id) for ascending price sort
        self._asks: SortedList[Order] = SortedList(
            key=lambda o: (o.price, o.created_at, o.id)
        )

    def add(self, order: Order) -> None:
        """Add an order to the book."""
        with self._lock:
            if order.id in self._orders:
                raise ValueError(f"Order already exists: {order.id}")

            self._orders[order.id] = order

            if order.side == OrderSide.BUY:
                self._bids.add(order)
            else:
                self._asks.add(order)

    def remove(self, order_id: str) -> Optional[Order]:
        """Remove an order from the book. Returns the order or None if not found."""
        with self._lock:
            order = self._orders.pop(order_id, None)
            if order is None:
                return None

            if order.side == OrderSide.BUY:
                self._bids.discard(order)
            else:
                self._asks.discard(order)

            return order

    def get(self, order_id: str) -> Optional[Order]:
        """Get an order by ID."""
        with self._lock:
            return self._orders.get(order_id)

    def get_best_bid(self) -> Optional[Order]:
        """Get the best (highest price) bid."""
        with self._lock:
            return self._bids[0] if self._bids else None

    def get_best_ask(self) -> Optional[Order]:
        """Get the best (lowest price) ask."""
        with self._lock:
            return self._asks[0] if self._asks else None

    def get_bids(self) -> list[Order]:
        """Get all bids in price-time priority order."""
        with self._lock:
            return list(self._bids)

    def get_asks(self) -> list[Order]:
        """Get all asks in price-time priority order."""
        with self._lock:
            return list(self._asks)

    def iter_matching_asks(self, max_price: Decimal) -> Iterator[Order]:
        """
        Iterate asks that could match a buy order at the given price.
        Yields asks with price <= max_price in price-time priority.
        """
        with self._lock:
            for order in self._asks:
                if order.price <= max_price:
                    yield order
                else:
                    break

    def iter_matching_bids(self, min_price: Decimal) -> Iterator[Order]:
        """
        Iterate bids that could match a sell order at the given price.
        Yields bids with price >= min_price in price-time priority.
        """
        with self._lock:
            for order in self._bids:
                if order.price >= min_price:
                    yield order
                else:
                    break

    def get_user_orders(self, address: str) -> list[Order]:
        """Get all orders for a specific user."""
        with self._lock:
            return [o for o in self._orders.values() if o.user_address == address]

    @property
    def bid_count(self) -> int:
        """Number of bids in the book."""
        with self._lock:
            return len(self._bids)

    @property
    def ask_count(self) -> int:
        """Number of asks in the book."""
        with self._lock:
            return len(self._asks)

    @property
    def order_count(self) -> int:
        """Total number of orders in the book."""
        with self._lock:
            return len(self._orders)

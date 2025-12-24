from decimal import Decimal
from typing import NamedTuple, Optional

from lumendark.models.order import Order, OrderSide
from lumendark.models.trade import Trade
from lumendark.storage.order_book import OrderBook


class MatchResult(NamedTuple):
    """Result of matching an incoming order."""

    trades: list[Trade]
    remaining_order: Optional[Order]  # None if fully filled, Order if has remaining qty


class MatchingEngine:
    """
    Price-time priority matching engine.

    Matches incoming orders against resting orders in the book.
    Trades execute at the resting order's price.
    """

    def __init__(self, order_book: OrderBook) -> None:
        self._book = order_book

    def match(self, incoming: Order) -> MatchResult:
        """
        Match an incoming order against the book.

        Returns a list of trades and the remaining order (if any).
        The incoming order is modified in place to reflect fills.
        Orders are removed from the book as they are fully filled.
        """
        if incoming.side == OrderSide.BUY:
            trades = self._match_buy(incoming)
        else:
            trades = self._match_sell(incoming)

        # Return remaining order if not fully filled
        remaining = incoming if incoming.remaining_quantity > Decimal("0") else None
        return MatchResult(trades=trades, remaining_order=remaining)

    def _match_buy(self, incoming: Order) -> list[Trade]:
        """Match a buy order against asks."""
        trades: list[Trade] = []

        # Get asks that could match (price <= incoming price)
        matching_asks = list(self._book.iter_matching_asks(incoming.price))

        for resting in matching_asks:
            if incoming.remaining_quantity <= Decimal("0"):
                break

            # Skip self-matching
            if resting.user_address == incoming.user_address:
                continue

            # Determine trade quantity
            trade_qty = min(incoming.remaining_quantity, resting.remaining_quantity)

            # Create trade at resting order's price
            trade = Trade.create(
                buyer_address=incoming.user_address,
                seller_address=resting.user_address,
                buy_order_id=incoming.id,
                sell_order_id=resting.id,
                price=resting.price,  # Execute at resting price
                quantity=trade_qty,
            )
            trades.append(trade)

            # Update order quantities
            incoming.fill(trade_qty)
            resting.fill(trade_qty)

            # Remove fully filled resting orders from book
            if resting.remaining_quantity == Decimal("0"):
                self._book.remove(resting.id)

        return trades

    def _match_sell(self, incoming: Order) -> list[Trade]:
        """Match a sell order against bids."""
        trades: list[Trade] = []

        # Get bids that could match (price >= incoming price)
        matching_bids = list(self._book.iter_matching_bids(incoming.price))

        for resting in matching_bids:
            if incoming.remaining_quantity <= Decimal("0"):
                break

            # Skip self-matching
            if resting.user_address == incoming.user_address:
                continue

            # Determine trade quantity
            trade_qty = min(incoming.remaining_quantity, resting.remaining_quantity)

            # Create trade at resting order's price
            trade = Trade.create(
                buyer_address=resting.user_address,
                seller_address=incoming.user_address,
                buy_order_id=resting.id,
                sell_order_id=incoming.id,
                price=resting.price,  # Execute at resting price
                quantity=trade_qty,
            )
            trades.append(trade)

            # Update order quantities
            incoming.fill(trade_qty)
            resting.fill(trade_qty)

            # Remove fully filled resting orders from book
            if resting.remaining_quantity == Decimal("0"):
                self._book.remove(resting.id)

        return trades

from decimal import Decimal

import pytest

from lumendark.models.order import Order, OrderSide, OrderStatus
from lumendark.storage.order_book import OrderBook
from lumendark.matching.engine import MatchingEngine


@pytest.fixture
def order_book() -> OrderBook:
    return OrderBook()


@pytest.fixture
def engine(order_book: OrderBook) -> MatchingEngine:
    return MatchingEngine(order_book)


class TestMatchingEngine:
    """Tests for the matching engine."""

    def test_buy_matches_best_ask(self, order_book: OrderBook, engine: MatchingEngine) -> None:
        """Buy order should match against the lowest priced ask first."""
        # Add asks at different prices
        ask1 = Order.create("seller1", OrderSide.SELL, Decimal("10.5"), Decimal("100"))
        ask2 = Order.create("seller2", OrderSide.SELL, Decimal("10.0"), Decimal("100"))  # Best
        ask3 = Order.create("seller3", OrderSide.SELL, Decimal("11.0"), Decimal("100"))

        order_book.add(ask1)
        order_book.add(ask2)
        order_book.add(ask3)

        # Buy order that can match
        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.5"), Decimal("50"))
        result = engine.match(buy)

        # Should match against best ask (seller2 @ 10.0)
        assert len(result.trades) == 1
        assert result.trades[0].seller_address == "seller2"
        assert result.trades[0].price == Decimal("10.0")  # Resting price
        assert result.trades[0].quantity == Decimal("50")
        assert result.remaining_order is None  # Fully filled

    def test_sell_matches_best_bid(self, order_book: OrderBook, engine: MatchingEngine) -> None:
        """Sell order should match against the highest priced bid first."""
        # Add bids at different prices
        bid1 = Order.create("buyer1", OrderSide.BUY, Decimal("9.5"), Decimal("100"))
        bid2 = Order.create("buyer2", OrderSide.BUY, Decimal("10.0"), Decimal("100"))  # Best
        bid3 = Order.create("buyer3", OrderSide.BUY, Decimal("9.0"), Decimal("100"))

        order_book.add(bid1)
        order_book.add(bid2)
        order_book.add(bid3)

        # Sell order that can match
        sell = Order.create("seller1", OrderSide.SELL, Decimal("9.5"), Decimal("50"))
        result = engine.match(sell)

        # Should match against best bid (buyer2 @ 10.0)
        assert len(result.trades) == 1
        assert result.trades[0].buyer_address == "buyer2"
        assert result.trades[0].price == Decimal("10.0")  # Resting price
        assert result.trades[0].quantity == Decimal("50")
        assert result.remaining_order is None

    def test_partial_fill_multiple_orders(
        self, order_book: OrderBook, engine: MatchingEngine
    ) -> None:
        """Large order should partially fill against multiple resting orders."""
        # Add asks
        ask1 = Order.create("seller1", OrderSide.SELL, Decimal("10.0"), Decimal("30"))
        ask2 = Order.create("seller2", OrderSide.SELL, Decimal("10.5"), Decimal("50"))

        order_book.add(ask1)
        order_book.add(ask2)

        # Buy order larger than first ask
        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.5"), Decimal("60"))
        result = engine.match(buy)

        # Should match both asks
        assert len(result.trades) == 2

        # First trade: 30 @ 10.0
        assert result.trades[0].quantity == Decimal("30")
        assert result.trades[0].price == Decimal("10.0")

        # Second trade: 30 @ 10.5
        assert result.trades[1].quantity == Decimal("30")
        assert result.trades[1].price == Decimal("10.5")

        assert result.remaining_order is None  # Fully filled (30 + 30 = 60)

    def test_remaining_quantity_added_to_book(
        self, order_book: OrderBook, engine: MatchingEngine
    ) -> None:
        """Unfilled portion should be returned for adding to book."""
        # Add small ask
        ask = Order.create("seller1", OrderSide.SELL, Decimal("10.0"), Decimal("30"))
        order_book.add(ask)

        # Buy order larger than available
        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.0"), Decimal("100"))
        result = engine.match(buy)

        # Should have one trade and remaining order
        assert len(result.trades) == 1
        assert result.trades[0].quantity == Decimal("30")

        assert result.remaining_order is not None
        assert result.remaining_order.remaining_quantity == Decimal("70")

    def test_no_match_when_prices_dont_cross(
        self, order_book: OrderBook, engine: MatchingEngine
    ) -> None:
        """No trades when bid price < ask price."""
        # Add ask at 11.0
        ask = Order.create("seller1", OrderSide.SELL, Decimal("11.0"), Decimal("100"))
        order_book.add(ask)

        # Buy at 10.0 (below ask)
        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.0"), Decimal("50"))
        result = engine.match(buy)

        # No match
        assert len(result.trades) == 0
        assert result.remaining_order is not None
        assert result.remaining_order.remaining_quantity == Decimal("50")

    def test_no_self_match(self, order_book: OrderBook, engine: MatchingEngine) -> None:
        """Orders from the same user should not match."""
        # Add ask from user1
        ask = Order.create("user1", OrderSide.SELL, Decimal("10.0"), Decimal("100"))
        order_book.add(ask)

        # Buy from same user1
        buy = Order.create("user1", OrderSide.BUY, Decimal("10.0"), Decimal("50"))
        result = engine.match(buy)

        # No match (same user)
        assert len(result.trades) == 0
        assert result.remaining_order is not None

    def test_price_time_priority(self, order_book: OrderBook, engine: MatchingEngine) -> None:
        """Earlier orders at same price should match first."""
        # Add asks at same price, different times
        ask1 = Order.create("seller1", OrderSide.SELL, Decimal("10.0"), Decimal("50"))
        ask2 = Order.create("seller2", OrderSide.SELL, Decimal("10.0"), Decimal("50"))

        order_book.add(ask1)  # Added first
        order_book.add(ask2)  # Added second

        # Buy that matches one order
        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.0"), Decimal("50"))
        result = engine.match(buy)

        # Should match first ask (seller1)
        assert len(result.trades) == 1
        assert result.trades[0].seller_address == "seller1"

        # ask2 should still be in book
        assert order_book.get(ask2.id) is not None

    def test_filled_orders_removed_from_book(
        self, order_book: OrderBook, engine: MatchingEngine
    ) -> None:
        """Fully filled resting orders should be removed from the book."""
        ask = Order.create("seller1", OrderSide.SELL, Decimal("10.0"), Decimal("100"))
        order_book.add(ask)

        # Buy exactly the ask quantity
        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.0"), Decimal("100"))
        result = engine.match(buy)

        # Order should be removed
        assert order_book.get(ask.id) is None
        assert order_book.ask_count == 0

    def test_partial_fill_leaves_order_in_book(
        self, order_book: OrderBook, engine: MatchingEngine
    ) -> None:
        """Partially filled resting orders should remain in the book."""
        ask = Order.create("seller1", OrderSide.SELL, Decimal("10.0"), Decimal("100"))
        order_book.add(ask)

        # Buy less than the ask quantity
        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.0"), Decimal("30"))
        result = engine.match(buy)

        # Order should still be in book with reduced quantity
        remaining_ask = order_book.get(ask.id)
        assert remaining_ask is not None
        assert remaining_ask.remaining_quantity == Decimal("70")
        assert remaining_ask.status == OrderStatus.PARTIALLY_FILLED

    def test_trade_value_calculation(
        self, order_book: OrderBook, engine: MatchingEngine
    ) -> None:
        """Trade value should be price * quantity."""
        ask = Order.create("seller1", OrderSide.SELL, Decimal("10.5"), Decimal("100"))
        order_book.add(ask)

        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.5"), Decimal("50"))
        result = engine.match(buy)

        trade = result.trades[0]
        assert trade.value == Decimal("525")  # 10.5 * 50
        assert trade.amount_a == Decimal("50")
        assert trade.amount_b == Decimal("525")

    def test_empty_book_no_match(self, order_book: OrderBook, engine: MatchingEngine) -> None:
        """No trades when book is empty."""
        buy = Order.create("buyer1", OrderSide.BUY, Decimal("10.0"), Decimal("50"))
        result = engine.match(buy)

        assert len(result.trades) == 0
        assert result.remaining_order is not None
        assert result.remaining_order.remaining_quantity == Decimal("50")


class TestOrderBook:
    """Tests for the order book."""

    def test_add_and_get(self, order_book: OrderBook) -> None:
        """Can add and retrieve orders."""
        order = Order.create("user1", OrderSide.BUY, Decimal("10.0"), Decimal("100"))
        order_book.add(order)

        retrieved = order_book.get(order.id)
        assert retrieved is not None
        assert retrieved.id == order.id

    def test_remove(self, order_book: OrderBook) -> None:
        """Can remove orders."""
        order = Order.create("user1", OrderSide.BUY, Decimal("10.0"), Decimal("100"))
        order_book.add(order)

        removed = order_book.remove(order.id)
        assert removed is not None
        assert order_book.get(order.id) is None

    def test_best_bid(self, order_book: OrderBook) -> None:
        """Best bid is highest price."""
        order_book.add(Order.create("u1", OrderSide.BUY, Decimal("9.0"), Decimal("100")))
        order_book.add(Order.create("u2", OrderSide.BUY, Decimal("10.0"), Decimal("100")))
        order_book.add(Order.create("u3", OrderSide.BUY, Decimal("9.5"), Decimal("100")))

        best = order_book.get_best_bid()
        assert best is not None
        assert best.price == Decimal("10.0")

    def test_best_ask(self, order_book: OrderBook) -> None:
        """Best ask is lowest price."""
        order_book.add(Order.create("u1", OrderSide.SELL, Decimal("11.0"), Decimal("100")))
        order_book.add(Order.create("u2", OrderSide.SELL, Decimal("10.0"), Decimal("100")))
        order_book.add(Order.create("u3", OrderSide.SELL, Decimal("10.5"), Decimal("100")))

        best = order_book.get_best_ask()
        assert best is not None
        assert best.price == Decimal("10.0")

    def test_user_orders(self, order_book: OrderBook) -> None:
        """Can get all orders for a user."""
        order_book.add(Order.create("user1", OrderSide.BUY, Decimal("10.0"), Decimal("100")))
        order_book.add(Order.create("user1", OrderSide.SELL, Decimal("11.0"), Decimal("100")))
        order_book.add(Order.create("user2", OrderSide.BUY, Decimal("9.0"), Decimal("100")))

        user1_orders = order_book.get_user_orders("user1")
        assert len(user1_orders) == 2

        user2_orders = order_book.get_user_orders("user2")
        assert len(user2_orders) == 1

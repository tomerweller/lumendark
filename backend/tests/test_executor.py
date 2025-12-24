from decimal import Decimal

import pytest

from lumendark.models.message import (
    Message,
    MessageType,
    MessageStatus,
)
from lumendark.models.order import OrderSide
from lumendark.storage.user_store import UserStore
from lumendark.storage.order_book import OrderBook
from lumendark.storage.message_store import MessageStore
from lumendark.queues.message_queue import MessageQueue
from lumendark.queues.action_queue import ActionQueue
from lumendark.executor.message_handler import MessageHandler


@pytest.fixture
def user_store() -> UserStore:
    return UserStore()


@pytest.fixture
def order_book() -> OrderBook:
    return OrderBook()


@pytest.fixture
def message_store() -> MessageStore:
    return MessageStore()


@pytest.fixture
def message_queue() -> MessageQueue:
    return MessageQueue()


@pytest.fixture
def action_queue() -> ActionQueue:
    return ActionQueue()


@pytest.fixture
def message_handler(
    message_queue: MessageQueue,
    action_queue: ActionQueue,
    user_store: UserStore,
    order_book: OrderBook,
    message_store: MessageStore,
) -> MessageHandler:
    return MessageHandler(
        message_queue=message_queue,
        action_queue=action_queue,
        user_store=user_store,
        order_book=order_book,
        message_store=message_store,
    )


class TestDepositProcessing:
    """Tests for deposit message processing."""

    @pytest.mark.asyncio
    async def test_deposit_increases_balance(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        message_store: MessageStore,
    ) -> None:
        """Deposit should increase user's available balance."""
        message = Message.create_deposit(
            user_address="user1",
            asset="a",
            amount="1000",
            ledger=100,
            tx_hash="abc123",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert message.status == MessageStatus.ACCEPTED
        assert user_store.get_available("user1", "a") == Decimal("1000")

    @pytest.mark.asyncio
    async def test_deposit_creates_user(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        message_store: MessageStore,
    ) -> None:
        """Deposit should create user if first time."""
        assert user_store.get("new_user") is None

        message = Message.create_deposit(
            user_address="new_user",
            asset="b",
            amount="500",
            ledger=100,
            tx_hash="abc123",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert user_store.get("new_user") is not None
        assert user_store.get_available("new_user", "b") == Decimal("500")

    @pytest.mark.asyncio
    async def test_deposit_invalid_amount_rejected(
        self,
        message_handler: MessageHandler,
        message_store: MessageStore,
    ) -> None:
        """Deposit with invalid amount should be rejected."""
        message = Message.create_deposit(
            user_address="user1",
            asset="a",
            amount="invalid",
            ledger=100,
            tx_hash="abc123",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert message.status == MessageStatus.REJECTED
        assert "Invalid amount" in str(message.rejection_reason)


class TestOrderProcessing:
    """Tests for order message processing."""

    @pytest.mark.asyncio
    async def test_order_allocates_liability(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        message_store: MessageStore,
    ) -> None:
        """Order should move funds from available to liabilities."""
        # Setup: deposit funds
        user_store.deposit("buyer1", "b", Decimal("1000"))

        # Place buy order: 10 A @ 50 B = 500 B required
        message = Message.create_order(
            user_address="buyer1",
            side="buy",
            price="50",
            quantity="10",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert message.status == MessageStatus.ACCEPTED
        assert user_store.get_available("buyer1", "b") == Decimal("500")
        assert user_store.get_liabilities("buyer1", "b") == Decimal("500")

    @pytest.mark.asyncio
    async def test_order_insufficient_balance_rejected(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        message_store: MessageStore,
    ) -> None:
        """Order without sufficient balance should be rejected."""
        user_store.deposit("buyer1", "b", Decimal("100"))

        # Try to place order requiring 500 B
        message = Message.create_order(
            user_address="buyer1",
            side="buy",
            price="50",
            quantity="10",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert message.status == MessageStatus.REJECTED
        assert "Insufficient balance" in str(message.rejection_reason)

    @pytest.mark.asyncio
    async def test_order_no_user_rejected(
        self,
        message_handler: MessageHandler,
        message_store: MessageStore,
    ) -> None:
        """Order from unknown user should be rejected."""
        message = Message.create_order(
            user_address="unknown",
            side="buy",
            price="50",
            quantity="10",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert message.status == MessageStatus.REJECTED
        assert "not found" in str(message.rejection_reason)

    @pytest.mark.asyncio
    async def test_order_added_to_book(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        order_book: OrderBook,
        message_store: MessageStore,
    ) -> None:
        """Non-matching order should be added to book."""
        user_store.deposit("seller1", "a", Decimal("100"))

        message = Message.create_order(
            user_address="seller1",
            side="sell",
            price="100",
            quantity="50",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert message.status == MessageStatus.ACCEPTED
        assert message.order_id is not None
        assert order_book.get(message.order_id) is not None

    @pytest.mark.asyncio
    async def test_order_matches_and_trades(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        order_book: OrderBook,
        action_queue: ActionQueue,
        message_store: MessageStore,
    ) -> None:
        """Matching orders should generate trades."""
        # Setup: seller has A, buyer has B
        user_store.deposit("seller1", "a", Decimal("100"))
        user_store.deposit("buyer1", "b", Decimal("1000"))

        # Seller places ask
        sell_msg = Message.create_order(
            user_address="seller1",
            side="sell",
            price="10",
            quantity="50",
        )
        message_store.add(sell_msg)
        await message_handler._process_message(sell_msg)

        # Buyer places matching bid
        buy_msg = Message.create_order(
            user_address="buyer1",
            side="buy",
            price="10",
            quantity="50",
        )
        message_store.add(buy_msg)
        await message_handler._process_message(buy_msg)

        # Should have 1 trade
        assert buy_msg.trades_count == 1

        # Action queue should have settlement
        assert not action_queue.empty

        # Balances should be updated
        # Buyer: paid 500 B, received 50 A
        assert user_store.get_available("buyer1", "a") == Decimal("50")
        assert user_store.get_available("buyer1", "b") == Decimal("500")
        # Seller: sold 50 A, received 500 B
        assert user_store.get_available("seller1", "a") == Decimal("50")
        assert user_store.get_available("seller1", "b") == Decimal("500")


class TestCancelProcessing:
    """Tests for cancel message processing."""

    @pytest.mark.asyncio
    async def test_cancel_releases_liability(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        order_book: OrderBook,
        message_store: MessageStore,
    ) -> None:
        """Cancel should release liabilities back to available."""
        user_store.deposit("user1", "a", Decimal("100"))

        # Place order
        order_msg = Message.create_order(
            user_address="user1",
            side="sell",
            price="10",
            quantity="50",
        )
        message_store.add(order_msg)
        await message_handler._process_message(order_msg)

        order_id = order_msg.order_id
        assert user_store.get_available("user1", "a") == Decimal("50")
        assert user_store.get_liabilities("user1", "a") == Decimal("50")

        # Cancel order
        cancel_msg = Message.create_cancel(
            user_address="user1",
            order_id=order_id,
        )
        message_store.add(cancel_msg)
        await message_handler._process_message(cancel_msg)

        assert cancel_msg.status == MessageStatus.ACCEPTED
        assert user_store.get_available("user1", "a") == Decimal("100")
        assert user_store.get_liabilities("user1", "a") == Decimal("0")
        assert order_book.get(order_id) is None

    @pytest.mark.asyncio
    async def test_cancel_other_user_rejected(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        order_book: OrderBook,
        message_store: MessageStore,
    ) -> None:
        """Cannot cancel another user's order."""
        user_store.deposit("user1", "a", Decimal("100"))

        # User1 places order
        order_msg = Message.create_order(
            user_address="user1",
            side="sell",
            price="10",
            quantity="50",
        )
        message_store.add(order_msg)
        await message_handler._process_message(order_msg)

        order_id = order_msg.order_id

        # User2 tries to cancel
        cancel_msg = Message.create_cancel(
            user_address="user2",
            order_id=order_id,
        )
        message_store.add(cancel_msg)
        await message_handler._process_message(cancel_msg)

        assert cancel_msg.status == MessageStatus.REJECTED
        assert "another user" in str(cancel_msg.rejection_reason)
        # Order should still be in book
        assert order_book.get(order_id) is not None

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_rejected(
        self,
        message_handler: MessageHandler,
        message_store: MessageStore,
    ) -> None:
        """Cannot cancel nonexistent order."""
        cancel_msg = Message.create_cancel(
            user_address="user1",
            order_id="nonexistent",
        )
        message_store.add(cancel_msg)
        await message_handler._process_message(cancel_msg)

        assert cancel_msg.status == MessageStatus.REJECTED
        assert "not found" in str(cancel_msg.rejection_reason)


class TestWithdrawProcessing:
    """Tests for withdrawal message processing."""

    @pytest.mark.asyncio
    async def test_withdraw_decreases_balance(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        action_queue: ActionQueue,
        message_store: MessageStore,
    ) -> None:
        """Withdrawal should decrease available balance and queue action."""
        user_store.deposit("user1", "a", Decimal("1000"))

        message = Message.create_withdraw(
            user_address="user1",
            asset="a",
            amount="500",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert message.status == MessageStatus.ACCEPTED
        assert user_store.get_available("user1", "a") == Decimal("500")
        assert not action_queue.empty

    @pytest.mark.asyncio
    async def test_withdraw_insufficient_rejected(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        message_store: MessageStore,
    ) -> None:
        """Withdrawal exceeding available should be rejected."""
        user_store.deposit("user1", "a", Decimal("100"))

        message = Message.create_withdraw(
            user_address="user1",
            asset="a",
            amount="500",
        )
        message_store.add(message)

        await message_handler._process_message(message)

        assert message.status == MessageStatus.REJECTED
        assert "Insufficient" in str(message.rejection_reason)

    @pytest.mark.asyncio
    async def test_withdraw_with_liabilities(
        self,
        message_handler: MessageHandler,
        user_store: UserStore,
        message_store: MessageStore,
    ) -> None:
        """Cannot withdraw funds locked in liabilities."""
        user_store.deposit("user1", "a", Decimal("100"))

        # Place order to lock 50 A
        order_msg = Message.create_order(
            user_address="user1",
            side="sell",
            price="10",
            quantity="50",
        )
        message_store.add(order_msg)
        await message_handler._process_message(order_msg)

        # Try to withdraw all 100 A
        withdraw_msg = Message.create_withdraw(
            user_address="user1",
            asset="a",
            amount="100",
        )
        message_store.add(withdraw_msg)
        await message_handler._process_message(withdraw_msg)

        assert withdraw_msg.status == MessageStatus.REJECTED

        # Can withdraw available 50 A
        withdraw_msg2 = Message.create_withdraw(
            user_address="user1",
            asset="a",
            amount="50",
        )
        message_store.add(withdraw_msg2)
        await message_handler._process_message(withdraw_msg2)

        assert withdraw_msg2.status == MessageStatus.ACCEPTED

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from lumendark.models.order import Order, OrderSide
from lumendark.models.trade import Trade
from lumendark.models.message import (
    IncomingMessage,
    MessageType,
    MessageStatus,
    OutgoingMessage,
)
from lumendark.storage.user_store import UserStore
from lumendark.storage.order_book import OrderBook
from lumendark.storage.message_store import MessageStore
from lumendark.queues.incoming import IncomingQueue
from lumendark.queues.outgoing import OutgoingQueue
from lumendark.matching.engine import MatchingEngine

logger = logging.getLogger(__name__)


class MainExecutor:
    """
    Main processing loop for incoming messages.

    Processes deposits, orders, cancels, and withdrawals sequentially.
    Trades are output to the outgoing queue for settlement.
    """

    def __init__(
        self,
        incoming_queue: IncomingQueue,
        outgoing_queue: OutgoingQueue,
        user_store: UserStore,
        order_book: OrderBook,
        message_store: MessageStore,
    ) -> None:
        self._incoming = incoming_queue
        self._outgoing = outgoing_queue
        self._users = user_store
        self._order_book = order_book
        self._messages = message_store
        self._engine = MatchingEngine(order_book)
        self._running = False

    async def start(self) -> None:
        """Start the executor loop."""
        self._running = True
        logger.info("MainExecutor started")

        while self._running:
            try:
                message = await self._incoming.get(timeout=1.0)
                if message is not None:
                    await self._process_message(message)
                    self._incoming.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error processing message: {e}")

        logger.info("MainExecutor stopped")

    async def stop(self) -> None:
        """Stop the executor loop."""
        self._running = False

    async def _process_message(self, message: IncomingMessage) -> None:
        """Process a single incoming message."""
        message.status = MessageStatus.PROCESSING
        self._messages.update(message)

        try:
            if message.type == MessageType.DEPOSIT:
                await self._process_deposit(message)
            elif message.type == MessageType.ORDER:
                await self._process_order(message)
            elif message.type == MessageType.CANCEL:
                await self._process_cancel(message)
            elif message.type == MessageType.WITHDRAW:
                await self._process_withdraw(message)
            else:
                message.reject(f"Unknown message type: {message.type}")
        except Exception as e:
            logger.exception(f"Error processing message {message.id}: {e}")
            message.reject(str(e))

        self._messages.update(message)

    async def _process_deposit(self, message: IncomingMessage) -> None:
        """Process a deposit message from blockchain event."""
        asset = message.payload["asset"]
        try:
            amount = Decimal(str(message.payload["amount"]))
        except (InvalidOperation, ValueError) as e:
            message.reject(f"Invalid amount: {e}")
            return

        if amount <= 0:
            message.reject("Amount must be positive")
            return

        self._users.deposit(message.user_address, asset, amount)
        message.accept()

        logger.info(f"Deposit processed: {message.user_address} +{amount} {asset}")

    async def _process_order(self, message: IncomingMessage) -> None:
        """Process a new order message."""
        # Parse order parameters
        try:
            side = OrderSide(message.payload["side"])
            price = Decimal(str(message.payload["price"]))
            quantity = Decimal(str(message.payload["quantity"]))
        except (ValueError, InvalidOperation) as e:
            message.reject(f"Invalid order parameters: {e}")
            return

        if price <= 0 or quantity <= 0:
            message.reject("Price and quantity must be positive")
            return

        # Check user exists
        user = self._users.get(message.user_address)
        if user is None:
            message.reject("User not found - deposit first")
            return

        # Calculate required balance for liability
        if side == OrderSide.BUY:
            required = price * quantity
            asset = "b"
        else:
            required = quantity
            asset = "a"

        # Check and allocate balance
        if not self._users.can_allocate(message.user_address, asset, required):
            available = self._users.get_available(message.user_address, asset)
            message.reject(f"Insufficient balance: have {available}, need {required}")
            return

        # Allocate funds (move from available to liabilities)
        self._users.allocate(message.user_address, asset, required)

        # Create order
        order = Order.create(
            user_address=message.user_address,
            side=side,
            price=price,
            quantity=quantity,
        )

        # Match against book
        result = self._engine.match(order)

        # Process trades
        for trade in result.trades:
            await self._process_trade(trade, order.side)

        # Add remaining to book if not fully filled
        if result.remaining_order is not None:
            self._order_book.add(result.remaining_order)
            message.order_id = result.remaining_order.id

        message.trades_count = len(result.trades)
        message.accept()

        logger.info(
            f"Order processed: {order.id}, {len(result.trades)} trades, "
            f"remaining={result.remaining_order.remaining_quantity if result.remaining_order else 0}"
        )

    async def _process_trade(self, trade: Trade, taker_side: OrderSide) -> None:
        """Process a trade and queue settlement."""
        # Update liabilities for both parties
        # The taker's liability was already allocated when the order was placed
        # The maker's liability needs to be consumed

        if taker_side == OrderSide.BUY:
            # Taker bought asset A, paid asset B
            # Taker: consume B liability (price * quantity)
            self._users.consume_liability(trade.buyer_address, "b", trade.amount_b)
            # Maker (seller): consume A liability (quantity)
            self._users.consume_liability(trade.seller_address, "a", trade.amount_a)
            # Credit: taker gets A, maker gets B
            self._users.credit(trade.buyer_address, "a", trade.amount_a)
            self._users.credit(trade.seller_address, "b", trade.amount_b)
        else:
            # Taker sold asset A, received asset B
            # Taker: consume A liability (quantity)
            self._users.consume_liability(trade.seller_address, "a", trade.amount_a)
            # Maker (buyer): consume B liability (price * quantity)
            self._users.consume_liability(trade.buyer_address, "b", trade.amount_b)
            # Credit: taker gets B, maker gets A
            self._users.credit(trade.seller_address, "b", trade.amount_b)
            self._users.credit(trade.buyer_address, "a", trade.amount_a)

        # Queue trade for on-chain settlement
        outgoing = OutgoingMessage.create_trade(
            trade_id=trade.id,
            buyer_address=trade.buyer_address,
            seller_address=trade.seller_address,
            amount_a=str(trade.amount_a),
            amount_b=str(trade.amount_b),
        )
        await self._outgoing.put(outgoing)

        logger.debug(f"Trade queued: {trade.id}")

    async def _process_cancel(self, message: IncomingMessage) -> None:
        """Process an order cancellation."""
        order_id = message.payload.get("order_id")
        if not order_id:
            message.reject("Missing order_id")
            return

        # Find and remove from book
        order = self._order_book.remove(order_id)
        if order is None:
            message.reject(f"Order not found: {order_id}")
            return

        # Verify ownership
        if order.user_address != message.user_address:
            # Put it back
            self._order_book.add(order)
            message.reject("Cannot cancel another user's order")
            return

        # Release liabilities back to available
        remaining = order.remaining_quantity
        if order.side == OrderSide.BUY:
            amount = order.price * remaining
            asset = "b"
        else:
            amount = remaining
            asset = "a"

        self._users.release(order.user_address, asset, amount)
        order.cancel()

        message.accept()
        logger.info(f"Order cancelled: {order_id}")

    async def _process_withdraw(self, message: IncomingMessage) -> None:
        """Process a withdrawal request."""
        asset = message.payload.get("asset")
        if asset not in ("a", "b"):
            message.reject(f"Invalid asset: {asset}")
            return

        try:
            amount = Decimal(str(message.payload["amount"]))
        except (InvalidOperation, ValueError, KeyError) as e:
            message.reject(f"Invalid amount: {e}")
            return

        if amount <= 0:
            message.reject("Amount must be positive")
            return

        # Check if user can withdraw
        if not self._users.can_withdraw(message.user_address, asset, amount):
            available = self._users.get_available(message.user_address, asset)
            message.reject(f"Insufficient available balance: have {available}, need {amount}")
            return

        # Decrease available balance
        self._users.withdraw(message.user_address, asset, amount)

        # Queue withdrawal for on-chain execution
        outgoing = OutgoingMessage.create_withdrawal(
            user_address=message.user_address,
            asset=asset,
            amount=str(amount),
        )
        await self._outgoing.put(outgoing)

        message.accept()
        logger.info(f"Withdrawal queued: {message.user_address} {amount} {asset}")

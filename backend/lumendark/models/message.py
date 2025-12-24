from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid


class MessageType(Enum):
    """Types of incoming messages."""

    DEPOSIT = "deposit"  # From blockchain event listener
    ORDER = "order"  # New limit order
    CANCEL = "cancel"  # Cancel existing order
    WITHDRAW = "withdraw"  # Withdrawal request


class MessageStatus(Enum):
    """Processing status of a message."""

    PENDING = "pending"  # Waiting in queue
    PROCESSING = "processing"  # Currently being processed
    ACCEPTED = "accepted"  # Successfully processed
    REJECTED = "rejected"  # Failed validation/processing


@dataclass
class IncomingMessage:
    """
    Message in the incoming queue.

    All user requests (orders, cancels, withdrawals) and blockchain events
    (deposits) are represented as incoming messages.
    """

    id: str
    type: MessageType
    user_address: str
    payload: dict[str, Any]
    status: MessageStatus = MessageStatus.PENDING
    rejection_reason: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: Optional[datetime] = None

    # Set after processing for ORDER messages
    order_id: Optional[str] = None
    trades_count: int = 0

    @staticmethod
    def create_deposit(
        user_address: str,
        asset: str,
        amount: str,
        ledger: int,
        tx_hash: str,
    ) -> "IncomingMessage":
        """Create a deposit message from a blockchain event."""
        return IncomingMessage(
            id=str(uuid.uuid4()),
            type=MessageType.DEPOSIT,
            user_address=user_address,
            payload={
                "asset": asset,
                "amount": amount,
                "ledger": ledger,
                "tx_hash": tx_hash,
            },
        )

    @staticmethod
    def create_order(
        user_address: str,
        side: str,
        price: str,
        quantity: str,
    ) -> "IncomingMessage":
        """Create an order message."""
        return IncomingMessage(
            id=str(uuid.uuid4()),
            type=MessageType.ORDER,
            user_address=user_address,
            payload={
                "side": side,
                "price": price,
                "quantity": quantity,
            },
        )

    @staticmethod
    def create_cancel(
        user_address: str,
        order_id: str,
    ) -> "IncomingMessage":
        """Create a cancel message."""
        return IncomingMessage(
            id=str(uuid.uuid4()),
            type=MessageType.CANCEL,
            user_address=user_address,
            payload={
                "order_id": order_id,
            },
        )

    @staticmethod
    def create_withdraw(
        user_address: str,
        asset: str,
        amount: str,
    ) -> "IncomingMessage":
        """Create a withdrawal message."""
        return IncomingMessage(
            id=str(uuid.uuid4()),
            type=MessageType.WITHDRAW,
            user_address=user_address,
            payload={
                "asset": asset,
                "amount": amount,
            },
        )

    def accept(self) -> None:
        """Mark message as accepted."""
        self.status = MessageStatus.ACCEPTED
        self.processed_at = datetime.now(timezone.utc)

    def reject(self, reason: str) -> None:
        """Mark message as rejected with a reason."""
        self.status = MessageStatus.REJECTED
        self.rejection_reason = reason
        self.processed_at = datetime.now(timezone.utc)


class OutgoingType(Enum):
    """Types of outgoing messages (to blockchain)."""

    WITHDRAWAL = "withdrawal"
    TRADE = "trade"


@dataclass
class OutgoingMessage:
    """
    Message in the outgoing queue.

    Represents actions that need to be submitted to the blockchain.
    """

    id: str
    type: OutgoingType
    payload: dict[str, Any]
    status: MessageStatus = MessageStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tx_hash: Optional[str] = None

    @staticmethod
    def create_withdrawal(
        user_address: str,
        asset: str,
        amount: str,
    ) -> "OutgoingMessage":
        """Create a withdrawal outgoing message."""
        return OutgoingMessage(
            id=str(uuid.uuid4()),
            type=OutgoingType.WITHDRAWAL,
            payload={
                "user": user_address,
                "asset": asset,
                "amount": amount,
            },
        )

    @staticmethod
    def create_trade(
        trade_id: str,
        buyer_address: str,
        seller_address: str,
        amount_a: str,
        amount_b: str,
    ) -> "OutgoingMessage":
        """Create a trade settlement outgoing message."""
        return OutgoingMessage(
            id=str(uuid.uuid4()),
            type=OutgoingType.TRADE,
            payload={
                "trade_id": trade_id,
                "buyer": buyer_address,
                "seller": seller_address,
                "amount_a": amount_a,
                "amount_b": amount_b,
            },
        )

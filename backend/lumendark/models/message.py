from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid


class MessageType(Enum):
    """Types of messages from users/blockchain."""

    DEPOSIT = "deposit"  # From blockchain event listener
    ORDER = "order"  # New limit order
    CANCEL = "cancel"  # Cancel existing order
    WITHDRAW = "withdraw"  # Withdrawal request


class MessageStatus(Enum):
    """Processing status of a message or action."""

    PENDING = "pending"  # Waiting in queue
    PROCESSING = "processing"  # Currently being processed
    ACCEPTED = "accepted"  # Successfully processed
    REJECTED = "rejected"  # Failed validation/processing


@dataclass
class Message:
    """
    Message from users or blockchain events.

    All user requests (orders, cancels, withdrawals) and blockchain events
    (deposits) are represented as messages and processed by the MessageHandler.
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
    ) -> "Message":
        """Create a deposit message from a blockchain event."""
        return Message(
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
    ) -> "Message":
        """Create an order message."""
        return Message(
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
    ) -> "Message":
        """Create a cancel message."""
        return Message(
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
    ) -> "Message":
        """Create a withdrawal message."""
        return Message(
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


class ActionType(Enum):
    """Types of actions to submit to the blockchain."""

    WITHDRAWAL = "withdrawal"
    SETTLEMENT = "settlement"


@dataclass
class Action:
    """
    Action to be submitted to the blockchain.

    Trade settlements and withdrawals are queued as actions and
    processed by the ActionHandler.
    """

    id: str
    type: ActionType
    payload: dict[str, Any]
    status: MessageStatus = MessageStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tx_hash: Optional[str] = None

    @staticmethod
    def create_withdrawal(
        user_address: str,
        asset: str,
        amount: str,
    ) -> "Action":
        """Create a withdrawal action."""
        return Action(
            id=str(uuid.uuid4()),
            type=ActionType.WITHDRAWAL,
            payload={
                "user": user_address,
                "asset": asset,
                "amount": amount,
            },
        )

    @staticmethod
    def create_settlement(
        trade_id: str,
        buyer_address: str,
        seller_address: str,
        amount_a: str,
        amount_b: str,
    ) -> "Action":
        """Create a trade settlement action."""
        return Action(
            id=str(uuid.uuid4()),
            type=ActionType.SETTLEMENT,
            payload={
                "trade_id": trade_id,
                "buyer": buyer_address,
                "seller": seller_address,
                "amount_a": amount_a,
                "amount_b": amount_b,
            },
        )

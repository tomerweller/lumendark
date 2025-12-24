"""Withdrawal API routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from lumendark.api.auth import verify_request_signature
from lumendark.api.dependencies import (
    get_message_queue,
    get_message_store,
)
from lumendark.models.message import Message
from lumendark.queues.message_queue import MessageQueue
from lumendark.storage.message_store import MessageStore

router = APIRouter(prefix="/withdrawals", tags=["withdrawals"])


class WithdrawalRequest(BaseModel):
    """Request body for a withdrawal."""

    asset: str = Field(..., pattern="^[ab]$", description="Asset to withdraw: a or b")
    amount: str = Field(..., description="Amount to withdraw (decimal string)")


class WithdrawalResponse(BaseModel):
    """Response after submitting a withdrawal request."""

    message_id: str = Field(..., description="Message ID to track withdrawal status")


@router.post("", response_model=WithdrawalResponse)
async def request_withdrawal(
    withdrawal: WithdrawalRequest,
    user_address: str = Depends(verify_request_signature),
    message_queue: MessageQueue = Depends(get_message_queue),
    message_store: MessageStore = Depends(get_message_store),
) -> WithdrawalResponse:
    """
    Request a withdrawal.

    The withdrawal request is placed in the message queue for processing.
    If approved, the funds will be transferred on-chain to the user's wallet.
    Returns a message_id that can be used to track the withdrawal status.
    """
    # Create message
    message = Message.create_withdraw(
        user_address=user_address,
        asset=withdrawal.asset,
        amount=withdrawal.amount,
    )

    # Store message for status tracking
    message_store.add(message)

    # Queue for processing
    await message_queue.put(message)

    return WithdrawalResponse(message_id=message.id)

"""Message status API routes."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lumendark.api.dependencies import get_message_store, get_user_store
from lumendark.models.message import MessageStatus
from lumendark.storage.message_store import MessageStore
from lumendark.storage.user_store import UserStore

router = APIRouter(prefix="/messages", tags=["status"])


class MessageStatusResponse(BaseModel):
    """Response for message status query."""

    message_id: str = Field(..., description="Message ID")
    type: str = Field(..., description="Message type (order, cancel, withdraw, deposit)")
    status: str = Field(..., description="Status (pending, processing, accepted, rejected)")
    rejection_reason: Optional[str] = Field(None, description="Reason if rejected")
    created_at: datetime = Field(..., description="When message was created")
    processed_at: Optional[datetime] = Field(None, description="When message was processed")

    # Order-specific fields
    order_id: Optional[str] = Field(None, description="Order ID if order was added to book")
    trades_count: Optional[int] = Field(None, description="Number of trades executed")


class BalanceResponse(BaseModel):
    """Response for balance query."""

    user_address: str = Field(..., description="User's Stellar address")
    asset_a_available: str = Field(..., description="Available balance of asset A")
    asset_a_liabilities: str = Field(..., description="Liabilities (locked in orders) of asset A")
    asset_b_available: str = Field(..., description="Available balance of asset B")
    asset_b_liabilities: str = Field(..., description="Liabilities (locked in orders) of asset B")


@router.get("/{message_id}", response_model=MessageStatusResponse)
async def get_message_status(
    message_id: str,
    message_store: MessageStore = Depends(get_message_store),
) -> MessageStatusResponse:
    """
    Get the status of a message.

    Use this endpoint to check if an order, cancel, or withdrawal
    request has been processed and whether it was accepted or rejected.
    """
    message = message_store.get(message_id)
    if message is None:
        raise HTTPException(
            status_code=404,
            detail=f"Message not found: {message_id}",
        )

    return MessageStatusResponse(
        message_id=message.id,
        type=message.type.value,
        status=message.status.value,
        rejection_reason=message.rejection_reason,
        created_at=message.created_at,
        processed_at=message.processed_at,
        order_id=message.order_id,
        trades_count=message.trades_count if message.trades_count > 0 else None,
    )


@router.get("/balances/{user_address}", response_model=BalanceResponse)
async def get_user_balance(
    user_address: str,
    user_store: UserStore = Depends(get_user_store),
) -> BalanceResponse:
    """
    Get a user's current balances.

    Returns both available balance and liabilities (funds locked in orders)
    for each asset.
    """
    return BalanceResponse(
        user_address=user_address,
        asset_a_available=str(user_store.get_available(user_address, "a")),
        asset_a_liabilities=str(user_store.get_liabilities(user_address, "a")),
        asset_b_available=str(user_store.get_available(user_address, "b")),
        asset_b_liabilities=str(user_store.get_liabilities(user_address, "b")),
    )

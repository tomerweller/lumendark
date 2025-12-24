"""Order API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lumendark.api.auth import verify_request_signature
from lumendark.api.dependencies import (
    get_incoming_queue,
    get_message_store,
)
from lumendark.models.message import IncomingMessage
from lumendark.queues.incoming import IncomingQueue
from lumendark.storage.message_store import MessageStore

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderRequest(BaseModel):
    """Request body for placing an order."""

    side: str = Field(..., pattern="^(buy|sell)$", description="Order side: buy or sell")
    price: str = Field(..., description="Limit price (decimal string)")
    quantity: str = Field(..., description="Order quantity (decimal string)")


class OrderResponse(BaseModel):
    """Response after submitting an order."""

    message_id: str = Field(..., description="Message ID to track order status")


class CancelRequest(BaseModel):
    """Request body for cancelling an order."""

    order_id: str = Field(..., description="Order ID to cancel")


class CancelResponse(BaseModel):
    """Response after submitting a cancel request."""

    message_id: str = Field(..., description="Message ID to track cancel status")


@router.post("", response_model=OrderResponse)
async def submit_order(
    order: OrderRequest,
    user_address: str = Depends(verify_request_signature),
    incoming_queue: IncomingQueue = Depends(get_incoming_queue),
    message_store: MessageStore = Depends(get_message_store),
) -> OrderResponse:
    """
    Submit a new limit order.

    The order is placed in the incoming queue for processing.
    Returns a message_id that can be used to track the order status.
    If the order is accepted and added to the book, the order_id will
    be available in the message status response.
    """
    # Create incoming message
    message = IncomingMessage.create_order(
        user_address=user_address,
        side=order.side,
        price=order.price,
        quantity=order.quantity,
    )

    # Store message for status tracking
    message_store.add(message)

    # Queue for processing
    await incoming_queue.put(message)

    return OrderResponse(message_id=message.id)


@router.post("/cancel", response_model=CancelResponse)
async def cancel_order(
    cancel: CancelRequest,
    user_address: str = Depends(verify_request_signature),
    incoming_queue: IncomingQueue = Depends(get_incoming_queue),
    message_store: MessageStore = Depends(get_message_store),
) -> CancelResponse:
    """
    Cancel an existing order.

    The cancel request is placed in the incoming queue for processing.
    Returns a message_id that can be used to track the cancel status.
    """
    # Create incoming message
    message = IncomingMessage.create_cancel(
        user_address=user_address,
        order_id=cancel.order_id,
    )

    # Store message for status tracking
    message_store.add(message)

    # Queue for processing
    await incoming_queue.put(message)

    return CancelResponse(message_id=message.id)

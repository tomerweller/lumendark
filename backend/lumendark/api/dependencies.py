"""FastAPI dependencies for accessing shared state."""

from typing import Optional

from lumendark.storage.user_store import UserStore
from lumendark.storage.order_book import OrderBook
from lumendark.storage.message_store import MessageStore
from lumendark.queues.incoming import IncomingQueue


class AppState:
    """
    Application state container.

    Holds references to all shared components accessed by API routes.
    """

    def __init__(self) -> None:
        self.user_store: Optional[UserStore] = None
        self.order_book: Optional[OrderBook] = None
        self.message_store: Optional[MessageStore] = None
        self.incoming_queue: Optional[IncomingQueue] = None


# Global app state instance
_app_state = AppState()


def get_app_state() -> AppState:
    """Get the global application state."""
    return _app_state


def get_user_store() -> UserStore:
    """FastAPI dependency for UserStore."""
    if _app_state.user_store is None:
        raise RuntimeError("UserStore not initialized")
    return _app_state.user_store


def get_order_book() -> OrderBook:
    """FastAPI dependency for OrderBook."""
    if _app_state.order_book is None:
        raise RuntimeError("OrderBook not initialized")
    return _app_state.order_book


def get_message_store() -> MessageStore:
    """FastAPI dependency for MessageStore."""
    if _app_state.message_store is None:
        raise RuntimeError("MessageStore not initialized")
    return _app_state.message_store


def get_incoming_queue() -> IncomingQueue:
    """FastAPI dependency for IncomingQueue."""
    if _app_state.incoming_queue is None:
        raise RuntimeError("IncomingQueue not initialized")
    return _app_state.incoming_queue

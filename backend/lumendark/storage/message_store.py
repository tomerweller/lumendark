from threading import RLock
from typing import Optional

from lumendark.models.message import Message


class MessageStore:
    """
    Thread-safe storage for message status tracking.

    Allows querying the status of submitted messages by ID.
    """

    def __init__(self) -> None:
        self._messages: dict[str, Message] = {}
        self._lock = RLock()

    def add(self, message: Message) -> None:
        """Add a message to the store."""
        with self._lock:
            self._messages[message.id] = message

    def get(self, message_id: str) -> Optional[Message]:
        """Get a message by ID."""
        with self._lock:
            return self._messages.get(message_id)

    def update(self, message: Message) -> None:
        """Update a message in the store."""
        with self._lock:
            self._messages[message.id] = message

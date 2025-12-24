import asyncio
from typing import Optional

from lumendark.models.message import Message


class MessageQueue:
    """
    Async queue for incoming messages.

    All user requests (orders, cancels, withdrawals) and blockchain events
    (deposits) are queued here for processing by the MessageHandler.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Message] = asyncio.Queue()

    async def put(self, message: Message) -> None:
        """Add a message to the queue."""
        await self._queue.put(message)

    async def get(self, timeout: Optional[float] = None) -> Optional[Message]:
        """
        Get a message from the queue.

        Args:
            timeout: Maximum time to wait in seconds. None for no timeout.

        Returns:
            The message, or None if timeout expired.
        """
        try:
            if timeout is None:
                return await self._queue.get()
            else:
                return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def task_done(self) -> None:
        """Mark the current task as done."""
        self._queue.task_done()

    @property
    def qsize(self) -> int:
        """Approximate queue size."""
        return self._queue.qsize()

    @property
    def empty(self) -> bool:
        """Whether the queue is empty."""
        return self._queue.empty()

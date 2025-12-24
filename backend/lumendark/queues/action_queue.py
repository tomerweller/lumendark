import asyncio
from typing import Optional

from lumendark.models.message import Action


class ActionQueue:
    """
    Async queue for blockchain actions.

    Trade settlements and withdrawals are queued here for submission
    to the blockchain by the ActionHandler.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Action] = asyncio.Queue()

    async def put(self, action: Action) -> None:
        """Add an action to the queue."""
        await self._queue.put(action)

    async def get(self, timeout: Optional[float] = None) -> Optional[Action]:
        """
        Get an action from the queue.

        Args:
            timeout: Maximum time to wait in seconds. None for no timeout.

        Returns:
            The action, or None if timeout expired.
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

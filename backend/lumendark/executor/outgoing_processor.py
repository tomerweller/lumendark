import asyncio
import logging
from typing import Optional, Protocol

from lumendark.models.message import OutgoingMessage, OutgoingType, MessageStatus
from lumendark.queues.outgoing import OutgoingQueue

logger = logging.getLogger(__name__)


class TransactionSubmitter(Protocol):
    """Protocol for submitting transactions to the blockchain."""

    async def submit_withdrawal(
        self,
        user: str,
        asset: str,
        amount: str,
    ) -> str:
        """Submit a withdrawal transaction. Returns tx hash."""
        ...

    async def submit_settlement(
        self,
        buyer: str,
        seller: str,
        amount_a: str,
        amount_b: str,
        trade_id: str,
    ) -> str:
        """Submit a settlement transaction. Returns tx hash."""
        ...


class OutgoingProcessor:
    """
    Processes outgoing queue items and submits transactions to Stellar.

    Takes messages from the outgoing queue and submits the corresponding
    transactions to the blockchain.
    """

    def __init__(
        self,
        outgoing_queue: OutgoingQueue,
        tx_submitter: TransactionSubmitter,
    ) -> None:
        self._outgoing = outgoing_queue
        self._tx_submitter = tx_submitter
        self._running = False

    async def start(self) -> None:
        """Start the processor loop."""
        self._running = True
        logger.info("OutgoingProcessor started")

        while self._running:
            try:
                message = await self._outgoing.get(timeout=1.0)
                if message is not None:
                    await self._process_message(message)
                    self._outgoing.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error processing outgoing message: {e}")

        logger.info("OutgoingProcessor stopped")

    async def stop(self) -> None:
        """Stop the processor loop."""
        self._running = False

    async def _process_message(self, message: OutgoingMessage) -> None:
        """Process a single outgoing message."""
        try:
            if message.type == OutgoingType.WITHDRAWAL:
                tx_hash = await self._tx_submitter.submit_withdrawal(
                    user=message.payload["user"],
                    asset=message.payload["asset"],
                    amount=message.payload["amount"],
                )
            elif message.type == OutgoingType.TRADE:
                tx_hash = await self._tx_submitter.submit_settlement(
                    buyer=message.payload["buyer"],
                    seller=message.payload["seller"],
                    amount_a=message.payload["amount_a"],
                    amount_b=message.payload["amount_b"],
                    trade_id=message.payload["trade_id"],
                )
            else:
                logger.error(f"Unknown outgoing type: {message.type}")
                message.status = MessageStatus.REJECTED
                return

            message.status = MessageStatus.ACCEPTED
            message.tx_hash = tx_hash
            logger.info(f"Transaction submitted: {tx_hash}")

        except Exception as e:
            message.status = MessageStatus.REJECTED
            logger.error(f"Transaction failed: {e}")


class MockTransactionSubmitter:
    """
    Mock transaction submitter for testing.

    Simply returns a fake tx hash without submitting to blockchain.
    """

    def __init__(self) -> None:
        self._tx_count = 0

    async def submit_withdrawal(
        self,
        user: str,
        asset: str,
        amount: str,
    ) -> str:
        """Mock withdrawal submission."""
        self._tx_count += 1
        tx_hash = f"mock_withdraw_tx_{self._tx_count}"
        logger.info(f"Mock withdrawal: {user} {amount} {asset} -> {tx_hash}")
        return tx_hash

    async def submit_settlement(
        self,
        buyer: str,
        seller: str,
        amount_a: str,
        amount_b: str,
        trade_id: str,
    ) -> str:
        """Mock settlement submission."""
        self._tx_count += 1
        tx_hash = f"mock_settle_tx_{self._tx_count}"
        logger.info(f"Mock settlement: {trade_id} {buyer}<->{seller} -> {tx_hash}")
        return tx_hash

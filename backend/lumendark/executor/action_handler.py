import asyncio
import logging
from typing import Optional, Protocol

from lumendark.models.message import Action, ActionType, MessageStatus
from lumendark.queues.action_queue import ActionQueue

logger = logging.getLogger(__name__)


class TransactionSubmitter(Protocol):
    """Protocol for submitting transactions to the blockchain."""

    async def submit_withdrawal(
        self,
        nonce: int,
        user: str,
        asset: str,
        amount: str,
    ) -> str:
        """Submit a withdrawal transaction. Returns tx hash."""
        ...

    async def submit_settlement(
        self,
        nonce: int,
        buyer: str,
        seller: str,
        amount_a: str,
        amount_b: str,
    ) -> str:
        """Submit a settlement transaction. Returns tx hash."""
        ...


class ActionHandler:
    """
    Processes actions and submits transactions to Stellar.

    Takes actions from the action queue and submits the corresponding
    transactions to the blockchain. Tracks a nonce to ensure sequential
    execution order on the contract.
    """

    def __init__(
        self,
        action_queue: ActionQueue,
        tx_submitter: TransactionSubmitter,
        initial_nonce: int = 0,
    ) -> None:
        self._actions = action_queue
        self._tx_submitter = tx_submitter
        self._running = False
        self._nonce = initial_nonce

    @property
    def nonce(self) -> int:
        """Get the current nonce value."""
        return self._nonce

    async def start(self) -> None:
        """Start the handler loop."""
        self._running = True
        logger.info("ActionHandler started")

        while self._running:
            try:
                action = await self._actions.get(timeout=1.0)
                if action is not None:
                    await self._process_action(action)
                    self._actions.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error processing action: {e}")

        logger.info("ActionHandler stopped")

    async def stop(self) -> None:
        """Stop the handler loop."""
        self._running = False

    async def _process_action(self, action: Action) -> None:
        """Process a single action."""
        try:
            current_nonce = self._nonce
            if action.type == ActionType.WITHDRAWAL:
                tx_hash = await self._tx_submitter.submit_withdrawal(
                    nonce=current_nonce,
                    user=action.payload["user"],
                    asset=action.payload["asset"],
                    amount=action.payload["amount"],
                )
            elif action.type == ActionType.SETTLEMENT:
                tx_hash = await self._tx_submitter.submit_settlement(
                    nonce=current_nonce,
                    buyer=action.payload["buyer"],
                    seller=action.payload["seller"],
                    amount_a=action.payload["amount_a"],
                    amount_b=action.payload["amount_b"],
                )
            else:
                logger.error(f"Unknown action type: {action.type}")
                action.status = MessageStatus.REJECTED
                return

            # Increment nonce after successful transaction
            self._nonce += 1
            action.status = MessageStatus.ACCEPTED
            action.tx_hash = tx_hash
            logger.info(f"Transaction submitted: {tx_hash} (nonce: {current_nonce} -> {self._nonce})")

        except Exception as e:
            action.status = MessageStatus.REJECTED
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
        nonce: int,
        user: str,
        asset: str,
        amount: str,
    ) -> str:
        """Mock withdrawal submission."""
        self._tx_count += 1
        tx_hash = f"mock_withdraw_tx_{self._tx_count}"
        logger.info(f"Mock withdrawal: nonce={nonce} {user} {amount} {asset} -> {tx_hash}")
        return tx_hash

    async def submit_settlement(
        self,
        nonce: int,
        buyer: str,
        seller: str,
        amount_a: str,
        amount_b: str,
    ) -> str:
        """Mock settlement submission."""
        self._tx_count += 1
        tx_hash = f"mock_settle_tx_{self._tx_count}"
        logger.info(f"Mock settlement: nonce={nonce} {buyer}<->{seller} -> {tx_hash}")
        return tx_hash

"""FastAPI application for Lumen Dark API."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from lumendark.api.dependencies import get_app_state
from lumendark.api.routes import orders, withdrawals, status
from lumendark.storage.user_store import UserStore
from lumendark.storage.order_book import OrderBook
from lumendark.storage.message_store import MessageStore
from lumendark.queues.incoming import IncomingQueue
from lumendark.queues.outgoing import OutgoingQueue
from lumendark.executor.main_executor import MainExecutor
from lumendark.executor.outgoing_processor import OutgoingProcessor
from lumendark.blockchain.client import SorobanClient
from lumendark.blockchain.event_listener import DepositEventListener
from lumendark.blockchain.transaction import TransactionSubmitter
from stellar_sdk import Keypair

logger = logging.getLogger(__name__)

# Testnet configuration - can be overridden via environment variables
ORDERBOOK_CONTRACT_ID = os.environ.get(
    "ORDERBOOK_CONTRACT_ID",
    "CDNTW7OWJF7LYWERWLQMUUCUIR5Q4XMFSXCHALRS3V3SN5KRDSCJT2DY"
)
SOROBAN_RPC_URL = os.environ.get(
    "SOROBAN_RPC_URL",
    "https://soroban-testnet.stellar.org"
)
# Admin secret key for signing settlement/withdrawal transactions
# This should be set via environment variable in production
ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY")


def create_app(
    user_store: Optional[UserStore] = None,
    order_book: Optional[OrderBook] = None,
    message_store: Optional[MessageStore] = None,
    incoming_queue: Optional[IncomingQueue] = None,
    outgoing_queue: Optional[OutgoingQueue] = None,
    run_executor: bool = True,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        user_store: UserStore instance (created if not provided)
        order_book: OrderBook instance (created if not provided)
        message_store: MessageStore instance (created if not provided)
        incoming_queue: IncomingQueue instance (created if not provided)
        outgoing_queue: OutgoingQueue instance (created if not provided)
        run_executor: Whether to run the MainExecutor in background

    Returns:
        Configured FastAPI application
    """
    # Create components if not provided
    user_store = user_store or UserStore()
    order_book = order_book or OrderBook()
    message_store = message_store or MessageStore()
    incoming_queue = incoming_queue or IncomingQueue()
    outgoing_queue = outgoing_queue or OutgoingQueue()

    # Store references for cleanup
    executor: Optional[MainExecutor] = None
    outgoing_processor: Optional[OutgoingProcessor] = None
    event_listener: Optional[DepositEventListener] = None
    executor_task: Optional[asyncio.Task] = None
    processor_task: Optional[asyncio.Task] = None
    listener_task: Optional[asyncio.Task] = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal executor, outgoing_processor, event_listener
        nonlocal executor_task, processor_task, listener_task

        # Initialize app state for dependencies
        app_state = get_app_state()
        app_state.user_store = user_store
        app_state.order_book = order_book
        app_state.message_store = message_store
        app_state.incoming_queue = incoming_queue

        if run_executor:
            # Create Soroban client first (used by both event listener and tx submitter)
            soroban_client = SorobanClient(
                rpc_url=SOROBAN_RPC_URL,
                contract_id=ORDERBOOK_CONTRACT_ID,
            )

            # Create and start the main executor
            executor = MainExecutor(
                incoming_queue=incoming_queue,
                outgoing_queue=outgoing_queue,
                user_store=user_store,
                order_book=order_book,
                message_store=message_store,
            )

            # Create outgoing processor with real transaction submitter
            if ADMIN_SECRET_KEY:
                admin_keypair = Keypair.from_secret(ADMIN_SECRET_KEY)
                tx_submitter = TransactionSubmitter(
                    client=soroban_client,
                    admin_keypair=admin_keypair,
                    contract_id=ORDERBOOK_CONTRACT_ID,
                )
                logger.info(f"Using real TransactionSubmitter with admin: {admin_keypair.public_key}")
            else:
                # Fall back to mock submitter if no admin key provided
                from lumendark.executor.outgoing_processor import MockTransactionSubmitter
                tx_submitter = MockTransactionSubmitter()
                logger.warning("No ADMIN_SECRET_KEY provided, using MockTransactionSubmitter")

            outgoing_processor = OutgoingProcessor(
                outgoing_queue=outgoing_queue,
                tx_submitter=tx_submitter,
            )

            async def on_deposit(message):
                """Handle deposit events from blockchain."""
                message_store.add(message)
                await incoming_queue.put(message)
                logger.info(f"Deposit detected: {message.user_address} {message.payload}")

            event_listener = DepositEventListener(
                client=soroban_client,
                on_deposit=on_deposit,
                poll_interval=5.0,  # Poll every 5 seconds
            )

            # Start background tasks
            executor_task = asyncio.create_task(executor.start())
            processor_task = asyncio.create_task(outgoing_processor.start())
            listener_task = asyncio.create_task(event_listener.start())

            logger.info(f"Started with contract {ORDERBOOK_CONTRACT_ID}")
            logger.info("Executor, processor, and event listener started")

        yield

        # Cleanup
        if run_executor:
            if executor:
                await executor.stop()
            if outgoing_processor:
                await outgoing_processor.stop()
            if event_listener:
                await event_listener.stop()
            if executor_task:
                executor_task.cancel()
                try:
                    await executor_task
                except asyncio.CancelledError:
                    pass
            if processor_task:
                processor_task.cancel()
                try:
                    await processor_task
                except asyncio.CancelledError:
                    pass
            if listener_task:
                listener_task.cancel()
                try:
                    await listener_task
                except asyncio.CancelledError:
                    pass

            logger.info("Executor, processor, and event listener stopped")

    app = FastAPI(
        title="Lumen Dark",
        description="Dark pool order book on Stellar network",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Include routes
    app.include_router(orders.router)
    app.include_router(withdrawals.router)
    app.include_router(status.router)

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy"}

    return app


# Default app instance for uvicorn
app = create_app()

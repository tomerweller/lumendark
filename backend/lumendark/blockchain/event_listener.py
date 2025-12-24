"""Deposit event listener for monitoring blockchain events."""

import asyncio
import logging
from typing import Optional, Callable, Awaitable, Any

from stellar_sdk import scval, Address

from lumendark.blockchain.client import SorobanClient
from lumendark.models.message import IncomingMessage

logger = logging.getLogger(__name__)

# Event topic for deposits (symbol "deposit")
DEPOSIT_TOPIC = "deposit"


def parse_scval_string(val: Any) -> str:
    """Parse a ScVal into a string representation."""
    # The value comes as XDR, we need to decode it
    if hasattr(val, 'sym'):
        return val.sym
    elif hasattr(val, 'address'):
        return str(val.address)
    elif hasattr(val, 'i128'):
        # i128 comes as two parts: hi and lo
        hi = val.i128.hi
        lo = val.i128.lo
        # Combine them into a single value
        return str((hi << 64) | lo)
    return str(val)


def decode_deposit_event(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Decode a deposit event from raw Soroban event data.

    Expected event structure (from contract):
    - topic[0]: "deposit" (symbol)
    - topic[1]: user address
    - value: (asset, amount) tuple where asset is enum and amount is i128

    Returns:
        Decoded event data or None if not a deposit event
    """
    try:
        topics = event.get("topic", [])
        if len(topics) < 2:
            return None

        # Decode topics from XDR
        from stellar_sdk import xdr as stellar_xdr

        # First topic should be "deposit"
        topic0 = stellar_xdr.SCVal.from_xdr(topics[0])
        if topic0.type.name != "SCV_SYMBOL":
            return None
        if topic0.sym.sc_symbol.decode() != DEPOSIT_TOPIC:
            return None

        # Second topic is user address
        topic1 = stellar_xdr.SCVal.from_xdr(topics[1])
        if topic1.type.name != "SCV_ADDRESS":
            return None
        user_address = Address.from_xdr_sc_address(
            topic1.address
        ).address

        # Value is a vec containing (asset_enum, amount)
        value_xdr = stellar_xdr.SCVal.from_xdr(event["value"])
        if value_xdr.type.name != "SCV_VEC":
            return None

        vec_items = value_xdr.vec.sc_vec
        if len(vec_items) < 2:
            return None

        # First item is asset enum (a vec with a symbol)
        asset_val = vec_items[0]
        if asset_val.type.name == "SCV_VEC" and len(asset_val.vec.sc_vec) > 0:
            inner = asset_val.vec.sc_vec[0]
            if inner.type.name == "SCV_SYMBOL":
                asset_symbol = inner.sym.sc_symbol.decode().lower()
            else:
                return None
        else:
            return None

        # Second item is amount (i128)
        amount_val = vec_items[1]
        if amount_val.type.name == "SCV_I128":
            hi = amount_val.i128.hi.int64
            lo = amount_val.i128.lo.uint64
            amount = (hi << 64) | lo
        else:
            return None

        return {
            "user_address": user_address,
            "asset": asset_symbol,
            "amount": str(amount),
            "ledger": event["ledger"],
            "tx_hash": event["tx_hash"],
        }

    except Exception as e:
        logger.warning(f"Failed to decode event: {e}", exc_info=True)
        return None


class DepositEventListener:
    """
    Listens for deposit events on the orderbook contract.

    Polls the Soroban RPC for new events and creates IncomingMessage
    objects for processing by the MainExecutor.
    """

    def __init__(
        self,
        client: SorobanClient,
        on_deposit: Callable[[IncomingMessage], Awaitable[None]],
        poll_interval: float = 5.0,
        start_ledger: Optional[int] = None,
    ) -> None:
        """
        Initialize the event listener.

        Args:
            client: SorobanClient for RPC communication
            on_deposit: Async callback to process deposit messages
            poll_interval: Seconds between polls
            start_ledger: Ledger to start listening from (defaults to latest)
        """
        self._client = client
        self._on_deposit = on_deposit
        self._poll_interval = poll_interval
        self._start_ledger = start_ledger
        self._running = False
        self._processed_events: set[str] = set()
        self._current_ledger: Optional[int] = None

    @property
    def current_ledger(self) -> Optional[int]:
        return self._current_ledger

    async def start(self) -> None:
        """Start the event listener loop."""
        self._running = True

        # Initialize starting ledger
        if self._start_ledger is not None:
            self._current_ledger = self._start_ledger
        else:
            self._current_ledger = self._client.get_latest_ledger()

        logger.info(
            f"DepositEventListener started from ledger {self._current_ledger}"
        )

        while self._running:
            try:
                await self._poll_events()
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error polling events: {e}")
                await asyncio.sleep(self._poll_interval)

        logger.info("DepositEventListener stopped")

    async def stop(self) -> None:
        """Stop the event listener loop."""
        self._running = False

    async def _poll_events(self) -> None:
        """Poll for new deposit events."""
        if self._current_ledger is None:
            return

        try:
            events = self._client.get_events(
                start_ledger=self._current_ledger,
                limit=100,
            )

            for event in events:
                event_id = event["id"]

                # Skip already processed events
                if event_id in self._processed_events:
                    continue

                # Try to decode as deposit event
                deposit_data = decode_deposit_event(event)
                if deposit_data is None:
                    continue

                # Create incoming message
                message = IncomingMessage.create_deposit(
                    user_address=deposit_data["user_address"],
                    asset=deposit_data["asset"],
                    amount=deposit_data["amount"],
                    ledger=deposit_data["ledger"],
                    tx_hash=deposit_data["tx_hash"],
                )

                logger.info(
                    f"Deposit event: {deposit_data['user_address']} "
                    f"+{deposit_data['amount']} {deposit_data['asset']}"
                )

                # Process the deposit
                await self._on_deposit(message)

                # Mark as processed
                self._processed_events.add(event_id)

                # Update current ledger
                if event["ledger"] >= self._current_ledger:
                    self._current_ledger = event["ledger"] + 1

            # Also update ledger if no events
            latest = self._client.get_latest_ledger()
            if latest > self._current_ledger:
                self._current_ledger = latest

            # Prune old processed events (keep last 10000)
            if len(self._processed_events) > 10000:
                # Convert to list, sort by event ID, keep newest
                sorted_events = sorted(self._processed_events)
                self._processed_events = set(sorted_events[-5000:])

        except Exception as e:
            logger.error(f"Failed to poll events: {e}")
            raise

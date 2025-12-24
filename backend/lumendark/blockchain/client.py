"""Soroban RPC client for interacting with Stellar network."""

import logging
from typing import Optional, Any

from stellar_sdk import Keypair, Network, SorobanServer, TransactionBuilder, scval
from stellar_sdk.soroban_rpc import EventFilter, EventFilterType

logger = logging.getLogger(__name__)

# Testnet configuration
TESTNET_RPC_URL = "https://soroban-testnet.stellar.org"
TESTNET_PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE


class SorobanClient:
    """
    Client for interacting with Soroban smart contracts.

    Handles RPC communication, transaction building, and event fetching.
    """

    def __init__(
        self,
        rpc_url: str = TESTNET_RPC_URL,
        network_passphrase: str = TESTNET_PASSPHRASE,
        contract_id: Optional[str] = None,
        admin_secret: Optional[str] = None,
    ) -> None:
        self._rpc_url = rpc_url
        self._network_passphrase = network_passphrase
        self._contract_id = contract_id
        self._admin_keypair: Optional[Keypair] = None

        if admin_secret:
            self._admin_keypair = Keypair.from_secret(admin_secret)

        self._server = SorobanServer(rpc_url)

    @property
    def contract_id(self) -> Optional[str]:
        return self._contract_id

    @contract_id.setter
    def contract_id(self, value: str) -> None:
        self._contract_id = value

    @property
    def admin_public_key(self) -> Optional[str]:
        if self._admin_keypair:
            return self._admin_keypair.public_key
        return None

    def get_latest_ledger(self) -> int:
        """Get the latest ledger sequence number."""
        response = self._server.get_latest_ledger()
        return response.sequence

    def get_events(
        self,
        start_ledger: int,
        contract_id: Optional[str] = None,
        topics: Optional[list[list[str]]] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Fetch events from the Soroban RPC.

        Args:
            start_ledger: Ledger to start fetching from
            contract_id: Filter by contract ID (uses default if not specified)
            topics: Optional topic filters
            limit: Maximum number of events to return

        Returns:
            List of event dictionaries
        """
        cid = contract_id or self._contract_id
        if not cid:
            raise ValueError("Contract ID must be specified")

        filters = [
            EventFilter(
                event_type=EventFilterType.CONTRACT,
                contract_ids=[cid],
            )
        ]

        response = self._server.get_events(
            start_ledger=start_ledger,
            filters=filters,
            limit=limit,
        )

        events = []
        for event in response.events:
            events.append({
                "id": event.id,
                "contract_id": event.contract_id,
                "ledger": event.ledger,
                "topic": event.topic,
                "value": event.value,
                "tx_hash": event.transaction_hash,
            })

        return events

    def build_transaction(
        self,
        source_account: str,
        base_fee: int = 100,
    ) -> TransactionBuilder:
        """
        Create a transaction builder for the source account.

        Args:
            source_account: Public key of the source account
            base_fee: Base fee in stroops

        Returns:
            TransactionBuilder ready for operations
        """
        account = self._server.load_account(source_account)
        return TransactionBuilder(
            source_account=account,
            network_passphrase=self._network_passphrase,
            base_fee=base_fee,
        )

    def submit_transaction(self, transaction_xdr: str) -> str:
        """
        Submit a signed transaction to the network.

        Args:
            transaction_xdr: Signed transaction in XDR format

        Returns:
            Transaction hash
        """
        response = self._server.send_transaction(transaction_xdr)

        if response.status == "ERROR":
            raise RuntimeError(f"Transaction failed: {response.error}")

        # Wait for transaction to complete
        tx_hash = response.hash

        # Poll for result
        import time
        for _ in range(30):  # 30 second timeout
            result = self._server.get_transaction(tx_hash)
            if result.status == "SUCCESS":
                return tx_hash
            elif result.status == "FAILED":
                raise RuntimeError(f"Transaction failed: {result}")
            elif result.status == "NOT_FOUND":
                time.sleep(1)
                continue
            else:
                time.sleep(1)

        raise TimeoutError(f"Transaction {tx_hash} did not complete in time")

    def simulate_transaction(self, transaction_xdr: str) -> dict[str, Any]:
        """
        Simulate a transaction to get resource estimates.

        Args:
            transaction_xdr: Unsigned transaction in XDR format

        Returns:
            Simulation result with resource estimates
        """
        response = self._server.simulate_transaction(transaction_xdr)
        return {
            "cost": response.cost if hasattr(response, 'cost') else None,
            "results": response.results if hasattr(response, 'results') else [],
            "error": response.error if hasattr(response, 'error') else None,
        }

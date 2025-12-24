"""Transaction submission for withdraw and settle operations."""

import logging
from typing import Optional

from stellar_sdk import (
    Keypair,
    TransactionBuilder,
    scval,
    Address,
)

from lumendark.blockchain.client import SorobanClient

logger = logging.getLogger(__name__)


class TransactionSubmitter:
    """
    Submits withdraw and settle transactions to the orderbook contract.

    All transactions are signed by the admin keypair.
    """

    def __init__(
        self,
        client: SorobanClient,
        admin_keypair: Keypair,
        contract_id: str,
    ) -> None:
        """
        Initialize the transaction submitter.

        Args:
            client: SorobanClient for RPC communication
            admin_keypair: Admin keypair for signing transactions
            contract_id: Orderbook contract ID
        """
        self._client = client
        self._admin_keypair = admin_keypair
        self._contract_id = contract_id

    async def submit_withdrawal(
        self,
        nonce: int,
        user: str,
        asset: str,
        amount: str,
    ) -> str:
        """
        Submit a withdrawal transaction.

        Args:
            nonce: Execution nonce for sequential ordering
            user: User's Stellar address
            asset: Asset symbol ("a" or "b")
            amount: Amount to withdraw (as string)

        Returns:
            Transaction hash
        """
        logger.info(f"Submitting withdrawal: nonce={nonce} {user} {amount} {asset}")

        # Build the contract call
        from stellar_sdk import SorobanServer
        from stellar_sdk.soroban_rpc import Api

        server = SorobanServer(self._client._rpc_url)

        # Load admin account
        admin_account = server.load_account(self._admin_keypair.public_key)

        # Build transaction with contract invocation
        builder = TransactionBuilder(
            source_account=admin_account,
            network_passphrase=self._client._network_passphrase,
            base_fee=100,
        )

        # Add contract invocation for withdraw
        # Contract signature: withdraw(nonce, user, asset, amount)
        builder.append_invoke_contract_function_op(
            contract_id=self._contract_id,
            function_name="withdraw",
            parameters=[
                scval.to_uint64(nonce),  # nonce (first param)
                scval.to_address(user),  # user address
                self._asset_to_scval(asset),  # asset enum
                scval.to_int128(int(amount)),  # amount
            ],
        )

        builder.set_timeout(30)
        tx = builder.build()

        # Simulate to get resource estimates
        sim_response = server.simulate_transaction(tx)

        if sim_response.error:
            raise RuntimeError(f"Simulation failed: {sim_response.error}")

        # Prepare transaction with simulation results
        tx = server.prepare_transaction(tx, sim_response)

        # Sign with admin key
        tx.sign(self._admin_keypair)

        # Submit
        response = server.send_transaction(tx)

        if response.status == "ERROR":
            raise RuntimeError(f"Transaction failed: {response.error}")

        tx_hash = response.hash

        # Wait for confirmation (60 seconds for testnet which can be slow)
        import time
        for _ in range(60):
            result = server.get_transaction(tx_hash)
            if result.status == "SUCCESS":
                logger.info(f"Withdrawal confirmed: {tx_hash}")
                return tx_hash
            elif result.status == "FAILED":
                raise RuntimeError(f"Withdrawal failed: {result}")
            time.sleep(1)

        raise TimeoutError(f"Withdrawal {tx_hash} did not confirm after 60s")

    async def submit_settlement(
        self,
        nonce: int,
        buyer: str,
        seller: str,
        amount_a: str,
        amount_b: str,
    ) -> str:
        """
        Submit a settlement transaction for a trade.

        In our order book, a trade always involves:
        - Seller selling asset A -> Buyer
        - Buyer paying asset B -> Seller

        Args:
            nonce: Execution nonce for sequential ordering
            buyer: Buyer's Stellar address (receives A, pays B)
            seller: Seller's Stellar address (sells A, receives B)
            amount_a: Amount of asset A transferred (seller -> buyer)
            amount_b: Amount of asset B transferred (buyer -> seller)

        Returns:
            Transaction hash
        """
        logger.info(
            f"Submitting settlement: nonce={nonce} "
            f"{seller} ->{amount_a}A-> {buyer}, "
            f"{buyer} ->{amount_b}B-> {seller}"
        )

        from stellar_sdk import SorobanServer

        server = SorobanServer(self._client._rpc_url)

        # Load admin account
        admin_account = server.load_account(self._admin_keypair.public_key)

        # Build transaction with contract invocation
        builder = TransactionBuilder(
            source_account=admin_account,
            network_passphrase=self._client._network_passphrase,
            base_fee=100,
        )

        # Contract signature:
        # settle(nonce, buyer, seller, asset_sold, amount_sold, asset_bought, amount_bought)
        # - asset_sold = A (what seller gives to buyer)
        # - asset_bought = B (what seller receives from buyer)
        builder.append_invoke_contract_function_op(
            contract_id=self._contract_id,
            function_name="settle",
            parameters=[
                scval.to_uint64(nonce),  # nonce (first param)
                scval.to_address(buyer),  # buyer address
                scval.to_address(seller),  # seller address
                self._asset_to_scval("a"),  # asset_sold = A
                scval.to_int128(int(float(amount_a))),  # amount_sold
                self._asset_to_scval("b"),  # asset_bought = B
                scval.to_int128(int(float(amount_b))),  # amount_bought
            ],
        )

        builder.set_timeout(30)
        tx = builder.build()

        # Simulate to get resource estimates
        sim_response = server.simulate_transaction(tx)

        if sim_response.error:
            raise RuntimeError(f"Simulation failed: {sim_response.error}")

        # Prepare transaction with simulation results
        tx = server.prepare_transaction(tx, sim_response)

        # Sign with admin key
        tx.sign(self._admin_keypair)

        # Submit
        response = server.send_transaction(tx)

        if response.status == "ERROR":
            raise RuntimeError(f"Transaction failed: {response.error}")

        tx_hash = response.hash

        # Wait for confirmation (60 seconds for testnet which can be slow)
        import time
        for _ in range(60):
            result = server.get_transaction(tx_hash)
            if result.status == "SUCCESS":
                logger.info(f"Settlement confirmed: {tx_hash}")
                return tx_hash
            elif result.status == "FAILED":
                raise RuntimeError(f"Settlement failed: {result}")
            time.sleep(1)

        raise TimeoutError(f"Settlement {tx_hash} did not confirm after 60s")

    def _asset_to_scval(self, asset: str):
        """Convert asset string to contract enum ScVal."""
        # Asset enum in contract: A or B
        if asset.lower() == "a":
            return scval.to_enum("A", None)
        elif asset.lower() == "b":
            return scval.to_enum("B", None)
        else:
            raise ValueError(f"Unknown asset: {asset}")

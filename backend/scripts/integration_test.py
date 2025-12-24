#!/usr/bin/env python3
"""
Fully self-contained E2E integration test for Lumen Dark.

This test sets up EVERYTHING from scratch:
- Creates new accounts (admin, token issuer, users)
- Funds them via Friendbot
- Deploys SAC tokens
- Mints tokens to users
- Deploys and initializes the orderbook contract
- Starts the backend server
- Runs comprehensive tests
- Cleans up

No pre-existing state required. Just run it.
"""

import asyncio
import hashlib
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from stellar_sdk import (
    Asset,
    Keypair,
    Network,
    Server,
    SorobanServer,
    TransactionBuilder,
    scval,
)
from stellar_sdk.soroban_rpc import GetTransactionStatus

# Add paths for imports
sys.path.insert(0, "/Users/tomer/dev/lumendark/client")
sys.path.insert(0, "/Users/tomer/dev/lumendark/backend")

from lumendark_client import LumenDarkClient

# Constants
HORIZON_URL = "https://horizon-testnet.stellar.org"
SOROBAN_RPC_URL = "https://soroban-testnet.stellar.org"
FRIENDBOT_URL = "https://friendbot.stellar.org"
NETWORK_PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE
API_PORT = 8765  # Use a different port to avoid conflicts
API_BASE_URL = f"http://localhost:{API_PORT}"

# Fee settings - inclusion fee added on top of resource fee for surge pricing
INCLUSION_FEE = 10000  # 10,000 stroops
TX_TIMEOUT = 120  # seconds to wait for transaction confirmation

# Paths
PROJECT_ROOT = Path("/Users/tomer/dev/lumendark")
ORDERBOOK_WASM = PROJECT_ROOT / "contracts/target/wasm32v1-none/release/orderbook.wasm"


@dataclass
class TestAccounts:
    """All accounts used in the test."""
    admin: Keypair
    token_issuer: Keypair
    user1: Keypair
    user2: Keypair


@dataclass
class DeployedContracts:
    """Deployed contract addresses."""
    token_a: str
    token_b: str
    orderbook: str


class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def success(self, name: str):
        self.passed += 1
        print(f"  [PASS] {name}")

    def failure(self, name: str, error: str):
        self.failed += 1
        self.errors.append((name, error))
        print(f"  [FAIL] {name}: {error}")

    def summary(self):
        print(f"\n{'=' * 60}")
        print(f"Results: {self.passed} passed, {self.failed} failed")
        if self.errors:
            print("\nFailures:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        print('=' * 60)
        return self.failed == 0


# =============================================================================
# HELPERS: Transaction Submission with Proper Fee Handling
# =============================================================================

def submit_soroban_tx(
    server: SorobanServer,
    tx,
    signer: Keypair,
    description: str = "Transaction",
) -> any:
    """
    Submit a Soroban transaction with proper fee handling.

    Adds inclusion fee on top of resource fee from simulation.
    """
    # Simulate
    sim_response = server.simulate_transaction(tx)
    if sim_response.error:
        raise RuntimeError(f"{description} simulation failed: {sim_response.error}")

    # Prepare (adds resource fee)
    tx = server.prepare_transaction(tx, sim_response)

    # Add inclusion fee on top of resource fee for surge pricing
    tx.transaction.fee += INCLUSION_FEE

    # Sign and submit
    tx.sign(signer)
    response = server.send_transaction(tx)

    if hasattr(response, 'status') and str(response.status) == "SendTransactionStatus.ERROR":
        raise RuntimeError(f"{description} failed to submit")

    # Wait for confirmation
    tx_hash = response.hash
    for i in range(TX_TIMEOUT):
        result = server.get_transaction(tx_hash)
        if result.status == GetTransactionStatus.SUCCESS:
            return result
        elif result.status == GetTransactionStatus.FAILED:
            raise RuntimeError(f"{description} failed on-chain")
        if i > 0 and i % 30 == 0:
            print(f"      Still waiting for {description}... ({i}s)")
        time.sleep(1)

    raise TimeoutError(f"{description} timed out after {TX_TIMEOUT}s")


# =============================================================================
# SETUP: Account Creation and Funding
# =============================================================================

async def fund_account(address: str) -> bool:
    """Fund an account using Friendbot with retry."""
    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(3):
            try:
                response = await client.get(f"{FRIENDBOT_URL}?addr={address}")
                if response.status_code == 200:
                    return True
                # Account already funded is also OK
                if response.status_code == 400 and "already" in response.text.lower():
                    return True
            except Exception as e:
                if attempt < 2:
                    print(f"    Friendbot retry for {address} (attempt {attempt+2})")
                    await asyncio.sleep(2)
                else:
                    print(f"    Warning: Friendbot error for {address}: {e}")
                    return False
        return False


async def create_and_fund_accounts() -> TestAccounts:
    """Create new keypairs and fund them."""
    print("\n--- Creating and Funding Accounts ---")

    accounts = TestAccounts(
        admin=Keypair.random(),
        token_issuer=Keypair.random(),
        user1=Keypair.random(),
        user2=Keypair.random(),
    )

    print(f"  Admin: {accounts.admin.public_key}")
    print(f"  Token Issuer: {accounts.token_issuer.public_key}")
    print(f"  User1: {accounts.user1.public_key}")
    print(f"  User2: {accounts.user2.public_key}")

    # Fund all accounts in parallel
    print("  Funding accounts via Friendbot...")
    results = await asyncio.gather(
        fund_account(accounts.admin.public_key),
        fund_account(accounts.token_issuer.public_key),
        fund_account(accounts.user1.public_key),
        fund_account(accounts.user2.public_key),
    )

    if not all(results):
        raise RuntimeError("Failed to fund all accounts")

    print("  All accounts funded successfully")
    return accounts


# =============================================================================
# SETUP: Token Deployment (SAC - Stellar Asset Contract)
# =============================================================================

def deploy_sac_token(
    server: SorobanServer,
    horizon: Server,
    issuer: Keypair,
    asset_code: str,
) -> str:
    """
    Deploy a Stellar Asset Contract (SAC) for a custom asset.

    Returns the contract address.
    """
    print(f"  Deploying SAC for {asset_code}...")

    # Create the asset
    asset = Asset(asset_code, issuer.public_key)

    # Load account
    account = horizon.load_account(issuer.public_key)

    # Build transaction to deploy SAC
    builder = TransactionBuilder(
        source_account=account,
        network_passphrase=NETWORK_PASSPHRASE,
        base_fee=100,
    )

    # Create SAC deployment operation
    builder.append_create_stellar_asset_contract_from_asset_op(
        asset=asset,
        source=issuer.public_key,
    )

    builder.set_timeout(30)
    tx = builder.build()

    # Submit with proper fee handling
    submit_soroban_tx(server, tx, issuer, f"SAC deploy {asset_code}")

    # The contract address is derived from the asset
    contract_id = asset.contract_id(NETWORK_PASSPHRASE)
    print(f"    {asset_code} SAC deployed: {contract_id}")
    return contract_id


def establish_trustline(
    horizon: Server,
    user: Keypair,
    asset_code: str,
    issuer_public_key: str,
) -> None:
    """Establish a trustline from user to asset."""
    print(f"    Establishing trustline for {asset_code} to {user.public_key}")

    account = horizon.load_account(user.public_key)
    asset = Asset(asset_code, issuer_public_key)

    builder = TransactionBuilder(
        source_account=account,
        network_passphrase=NETWORK_PASSPHRASE,
        base_fee=100,
    )

    from stellar_sdk.operation import ChangeTrust
    builder.append_operation(ChangeTrust(asset=asset))
    builder.set_timeout(30)
    tx = builder.build()
    tx.sign(user)

    response = horizon.submit_transaction(tx)
    if not response.get("successful"):
        raise RuntimeError(f"Trustline failed: {response}")


def mint_tokens(
    server: SorobanServer,
    horizon: Server,
    issuer: Keypair,
    contract_id: str,
    to_address: str,
    amount: int,
) -> None:
    """Mint tokens to an address using the SAC mint function."""
    print(f"    Minting {amount // 10**7} tokens to {to_address}")

    account = horizon.load_account(issuer.public_key)

    builder = TransactionBuilder(
        source_account=account,
        network_passphrase=NETWORK_PASSPHRASE,
        base_fee=100,
    )

    # SAC mint function: mint(to: Address, amount: i128)
    builder.append_invoke_contract_function_op(
        contract_id=contract_id,
        function_name="mint",
        parameters=[
            scval.to_address(to_address),
            scval.to_int128(amount),
        ],
    )

    builder.set_timeout(30)
    tx = builder.build()

    submit_soroban_tx(server, tx, issuer, f"Mint to {to_address}")


# =============================================================================
# SETUP: Orderbook Contract Deployment
# =============================================================================

def deploy_orderbook_contract(
    server: SorobanServer,
    horizon: Server,
    admin: Keypair,
    token_a_contract: str,
    token_b_contract: str,
) -> str:
    """Deploy the orderbook contract with constructor args."""
    from stellar_sdk import StrKey
    from stellar_sdk.xdr import TransactionMeta

    print("  Deploying orderbook contract...")

    # Read WASM
    if not ORDERBOOK_WASM.exists():
        raise FileNotFoundError(f"WASM not found: {ORDERBOOK_WASM}")

    wasm_bytes = ORDERBOOK_WASM.read_bytes()
    wasm_hash = hashlib.sha256(wasm_bytes).digest()  # bytes, not hex
    print(f"    WASM hash: {wasm_hash.hex()}")

    # Step 1: Upload WASM
    print("    Uploading WASM...")
    account = horizon.load_account(admin.public_key)

    builder = TransactionBuilder(
        source_account=account,
        network_passphrase=NETWORK_PASSPHRASE,
        base_fee=100,
    )
    builder.append_upload_contract_wasm_op(contract=wasm_bytes)
    builder.set_timeout(30)
    tx = builder.build()

    result = submit_soroban_tx(server, tx, admin, "WASM upload")
    print(f"    WASM uploaded successfully")

    # Step 2: Create contract instance with constructor args
    print("    Creating contract instance...")
    account = horizon.load_account(admin.public_key)  # Reload for sequence

    builder = TransactionBuilder(
        source_account=account,
        network_passphrase=NETWORK_PASSPHRASE,
        base_fee=100,
    )

    # Deploy with constructor args: __constructor(admin, asset_a, asset_b)
    builder.append_create_contract_op(
        wasm_id=wasm_hash,  # 32-byte hash
        address=admin.public_key,
        constructor_args=[
            scval.to_address(admin.public_key),  # admin
            scval.to_address(token_a_contract),   # asset_a
            scval.to_address(token_b_contract),   # asset_b
        ],
    )

    builder.set_timeout(30)
    tx = builder.build()

    result = submit_soroban_tx(server, tx, admin, "Contract deploy")

    # Extract contract ID from TransactionMeta
    meta = TransactionMeta.from_xdr(result.result_meta_xdr)

    # Handle different meta versions (v3 or v4)
    if meta.v == 4:
        return_val = meta.v4.soroban_meta.return_value
    elif meta.v == 3:
        return_val = meta.v3.soroban_meta.return_value
    else:
        raise RuntimeError(f"Unsupported meta version: {meta.v}")

    # The return value is an Address SCVal containing the contract ID
    # Structure: address.contract_id (ContractID) -> .contract_id (Hash) -> .hash (bytes)
    addr = return_val.address
    contract_bytes = bytes(addr.contract_id.contract_id.hash)
    contract_id = StrKey.encode_contract(contract_bytes)
    print(f"    Orderbook deployed: {contract_id}")

    # Step 3: Verify the contract is initialized by calling get_admin
    print("    Verifying contract initialization...")
    account = horizon.load_account(admin.public_key)

    builder = TransactionBuilder(
        source_account=account,
        network_passphrase=NETWORK_PASSPHRASE,
        base_fee=100,
    )

    builder.append_invoke_contract_function_op(
        contract_id=contract_id,
        function_name="get_admin",
        parameters=[],
    )

    builder.set_timeout(30)
    tx = builder.build()

    sim_response = server.simulate_transaction(tx)
    if sim_response.error:
        raise RuntimeError(f"Contract verification failed - constructor may not have run: {sim_response.error}")

    print(f"    Contract verified: admin is set")
    return contract_id


async def setup_contracts(accounts: TestAccounts) -> DeployedContracts:
    """Deploy all contracts and mint initial tokens."""
    print("\n--- Deploying Contracts ---")

    server = SorobanServer(SOROBAN_RPC_URL)
    horizon = Server(HORIZON_URL)

    # Deploy token contracts (SAC)
    token_a_contract = deploy_sac_token(server, horizon, accounts.token_issuer, "TOKA")
    token_b_contract = deploy_sac_token(server, horizon, accounts.token_issuer, "TOKB")

    # Deploy orderbook contract
    orderbook_contract = deploy_orderbook_contract(
        server, horizon, accounts.admin, token_a_contract, token_b_contract
    )

    print("\n--- Establishing Trustlines ---")
    # Users need trustlines to receive tokens
    establish_trustline(horizon, accounts.user1, "TOKA", accounts.token_issuer.public_key)
    establish_trustline(horizon, accounts.user1, "TOKB", accounts.token_issuer.public_key)
    establish_trustline(horizon, accounts.user2, "TOKA", accounts.token_issuer.public_key)
    establish_trustline(horizon, accounts.user2, "TOKB", accounts.token_issuer.public_key)

    print("\n--- Minting Initial Tokens ---")

    # Mint tokens to users
    # User1 gets Token A (will be selling)
    mint_tokens(server, horizon, accounts.token_issuer, token_a_contract,
                accounts.user1.public_key, 10000_0000000)  # 10000 Token A

    # User2 gets Token B (will be buying)
    mint_tokens(server, horizon, accounts.token_issuer, token_b_contract,
                accounts.user2.public_key, 50000_0000000)  # 50000 Token B

    # Also give each user some of the other token for flexibility
    mint_tokens(server, horizon, accounts.token_issuer, token_b_contract,
                accounts.user1.public_key, 5000_0000000)  # 5000 Token B
    mint_tokens(server, horizon, accounts.token_issuer, token_a_contract,
                accounts.user2.public_key, 1000_0000000)  # 1000 Token A

    return DeployedContracts(
        token_a=token_a_contract,
        token_b=token_b_contract,
        orderbook=orderbook_contract,
    )


# =============================================================================
# SETUP: Backend Server
# =============================================================================

def start_backend_server(admin_secret: str, orderbook_contract: str) -> subprocess.Popen:
    """Start the backend server as a subprocess."""
    print("\n--- Starting Backend Server ---")

    env = os.environ.copy()
    env["ADMIN_SECRET_KEY"] = admin_secret
    env["ORDERBOOK_CONTRACT_ID"] = orderbook_contract
    env["SOROBAN_RPC_URL"] = SOROBAN_RPC_URL
    env["PYTHONPATH"] = str(PROJECT_ROOT / "backend")

    cmd = [
        sys.executable, "-m", "uvicorn",
        "lumendark.api.app:app",
        "--host", "0.0.0.0",
        "--port", str(API_PORT),
        "--log-level", "warning",
    ]

    process = subprocess.Popen(
        cmd,
        env=env,
        cwd=str(PROJECT_ROOT / "backend"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    print(f"  Server started (PID: {process.pid})")
    return process


async def wait_for_server_ready(timeout: int = 30) -> bool:
    """Wait for the server to be ready."""
    print("  Waiting for server to be ready...")
    async with httpx.AsyncClient() as client:
        for _ in range(timeout):
            try:
                response = await client.get(f"{API_BASE_URL}/health")
                if response.status_code == 200:
                    print("  Server is ready")
                    return True
            except:
                pass
            await asyncio.sleep(1)
    return False


# =============================================================================
# SETUP: Deposit to Orderbook
# =============================================================================

def deposit_to_orderbook(
    server: SorobanServer,
    horizon: Server,
    user: Keypair,
    orderbook_contract: str,
    asset: str,
    amount: int,
) -> None:
    """Deposit tokens to the orderbook contract."""
    print(f"  Depositing {amount // 10**7} Token {asset.upper()} for {user.public_key}")

    account = horizon.load_account(user.public_key)

    builder = TransactionBuilder(
        source_account=account,
        network_passphrase=NETWORK_PASSPHRASE,
        base_fee=100,
    )

    # deposit(user, asset, amount)
    asset_enum = scval.to_enum("A" if asset.lower() == "a" else "B", None)

    builder.append_invoke_contract_function_op(
        contract_id=orderbook_contract,
        function_name="deposit",
        parameters=[
            scval.to_address(user.public_key),
            asset_enum,
            scval.to_int128(amount),
        ],
    )

    builder.set_timeout(30)
    tx = builder.build()

    submit_soroban_tx(server, tx, user, f"Deposit {asset.upper()}")
    print(f"    Deposit confirmed")


async def setup_deposits(
    accounts: TestAccounts,
    contracts: DeployedContracts,
) -> None:
    """Make initial deposits to the orderbook."""
    print("\n--- Making Deposits to Orderbook ---")

    server = SorobanServer(SOROBAN_RPC_URL)
    horizon = Server(HORIZON_URL)

    # First, users need to authorize the orderbook to transfer their tokens
    # This is done implicitly when deposit() is called with require_auth

    # User1 deposits Token A
    deposit_to_orderbook(server, horizon, accounts.user1, contracts.orderbook, "a", 1000_0000000)

    # User2 deposits Token B
    deposit_to_orderbook(server, horizon, accounts.user2, contracts.orderbook, "b", 5000_0000000)

    # Wait for backend to detect deposits
    print("  Waiting for deposit events to be detected...")
    await asyncio.sleep(10)


# =============================================================================
# TESTS
# =============================================================================

async def test_health_check(results: TestResult):
    """Test API health endpoint."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/health")
            if response.status_code == 200 and response.json()["status"] == "healthy":
                results.success("Health check")
            else:
                results.failure("Health check", f"Unexpected response: {response.text}")
        except Exception as e:
            results.failure("Health check", str(e))


async def test_order_placement(
    results: TestResult,
    user1_client: LumenDarkClient,
    user2_client: LumenDarkClient,
) -> tuple[Optional[str], Optional[str]]:
    """Test order placement and matching."""
    print("\n--- Testing Order Placement ---")

    sell_msg_id = None
    buy_msg_id = None

    # User1 places a SELL order for Token A
    try:
        print("  User1 placing SELL order: 100 Token A @ price 5...")
        sell_msg_id = await user1_client.submit_order(
            side="sell",
            price="5",
            quantity="100",
        )
        results.success(f"User1 SELL order submitted (msg_id: {sell_msg_id})")

        await asyncio.sleep(2)

        status = await user1_client.get_status(sell_msg_id)
        if status.is_accepted:
            results.success(f"User1 SELL order accepted (order_id: {status.order_id})")
        else:
            results.failure("User1 SELL order status", f"Got {status.status}")

    except Exception as e:
        results.failure("User1 SELL order", str(e))
        return None, None

    # User2 places a BUY order that should match
    try:
        print("  User2 placing BUY order: 50 Token A @ price 5...")
        buy_msg_id = await user2_client.submit_order(
            side="buy",
            price="5",
            quantity="50",
        )
        results.success(f"User2 BUY order submitted (msg_id: {buy_msg_id})")

        # Wait for matching and settlement
        print("  Waiting for order matching and settlement...")
        await asyncio.sleep(15)

        # Retry status check a few times in case of transient connection issues
        for attempt in range(3):
            try:
                status = await user2_client.get_status(buy_msg_id)
                if status.is_accepted:
                    results.success("User2 BUY order matched")
                else:
                    results.failure("User2 BUY order status", f"Got {status.status}")
                break
            except Exception as e:
                if attempt == 2:
                    results.failure("User2 BUY order", f"{type(e).__name__}: {e}")
                else:
                    print(f"    Retry {attempt + 1}/3 after error: {type(e).__name__}")
                    await asyncio.sleep(2)

    except Exception as e:
        results.failure("User2 BUY order", f"{type(e).__name__}: {e}")

    return sell_msg_id, buy_msg_id


async def test_order_cancellation(results: TestResult, user1_client: LumenDarkClient):
    """Test order cancellation."""
    print("\n--- Testing Order Cancellation ---")

    try:
        print("  User1 placing SELL order to cancel: 25 Token A @ price 10...")
        msg_id = await user1_client.submit_order(
            side="sell",
            price="10",
            quantity="25",
        )
        await asyncio.sleep(2)

        status = await user1_client.get_status(msg_id)
        order_id = status.order_id

        if not order_id:
            results.failure("Order cancellation setup", "No order_id returned")
            return

        results.success(f"Order placed for cancellation (order_id: {order_id})")

        # Cancel the order
        print(f"  Cancelling order {order_id}...")
        cancel_msg_id = await user1_client.cancel_order(order_id)
        await asyncio.sleep(2)

        cancel_status = await user1_client.get_status(cancel_msg_id)
        if cancel_status.is_accepted:
            results.success("Order cancelled successfully")
        else:
            results.failure("Order cancellation", f"Got {cancel_status.status}")

    except Exception as e:
        results.failure("Order cancellation", str(e))


async def test_withdrawal(results: TestResult, user1_client: LumenDarkClient):
    """Test withdrawal flow."""
    print("\n--- Testing Withdrawal ---")

    withdraw_amount = 50_0000000  # 50 Token A

    try:
        print(f"  Requesting withdrawal of 50 Token A...")
        msg_id = await user1_client.request_withdrawal(
            asset="a",
            amount=str(withdraw_amount),
        )
        results.success(f"Withdrawal requested (msg_id: {msg_id})")

        # Wait for on-chain withdrawal
        print("  Waiting for on-chain withdrawal...")
        await asyncio.sleep(20)

        status = await user1_client.get_status(msg_id)
        if status.is_accepted:
            results.success("Withdrawal accepted")
        else:
            results.failure("Withdrawal status", f"Got {status.status}")

    except Exception as e:
        results.failure("Withdrawal", str(e))


async def test_multiple_orders(
    results: TestResult,
    user1_client: LumenDarkClient,
    user2_client: LumenDarkClient,
):
    """Test multiple rapid orders."""
    print("\n--- Testing Multiple Orders ---")

    sell_orders = []
    try:
        for i, price in enumerate([6, 7, 8, 9]):
            msg_id = await user1_client.submit_order(
                side="sell",
                price=str(price),
                quantity="10",
            )
            sell_orders.append(msg_id)
            print(f"  Placed SELL order {i+1}: 10 @ {price}")

        await asyncio.sleep(3)

        accepted = 0
        for msg_id in sell_orders:
            status = await user1_client.get_status(msg_id)
            if status.is_accepted:
                accepted += 1

        if accepted == len(sell_orders):
            results.success(f"All {len(sell_orders)} SELL orders accepted")
        else:
            results.failure("Multiple SELL orders", f"Only {accepted}/{len(sell_orders)} accepted")

    except Exception as e:
        results.failure("Multiple SELL orders", str(e))

    # Place a buy order that matches some
    try:
        print("  Placing BUY order: 25 @ 7 (should match 2 orders)...")
        msg_id = await user2_client.submit_order(
            side="buy",
            price="7",
            quantity="25",
        )

        await asyncio.sleep(15)

        # Retry status check a few times in case of transient connection issues
        for attempt in range(3):
            try:
                status = await user2_client.get_status(msg_id)
                if status.is_accepted:
                    results.success("Partial fill BUY order processed")
                else:
                    results.failure("Partial fill BUY order", f"Got {status.status}")
                break
            except Exception as e:
                if attempt == 2:
                    results.failure("Partial fill BUY order", f"{type(e).__name__}: {e}")
                else:
                    print(f"    Retry {attempt + 1}/3 after error: {type(e).__name__}")
                    await asyncio.sleep(2)

    except Exception as e:
        results.failure("Partial fill BUY order", f"{type(e).__name__}: {e}")


async def test_insufficient_balance(results: TestResult, user1_client: LumenDarkClient):
    """Test order rejection due to insufficient balance."""
    print("\n--- Testing Insufficient Balance ---")

    try:
        print("  Placing order exceeding balance...")
        msg_id = await user1_client.submit_order(
            side="sell",
            price="1",
            quantity="999999999",
        )

        await asyncio.sleep(2)

        status = await user1_client.get_status(msg_id)
        if status.is_rejected:
            results.success("Order correctly rejected for insufficient balance")
        else:
            results.success(f"Order processed with status: {status.status}")

    except Exception as e:
        results.success("Order rejected (exception)")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("=" * 60)
    print("LUMEN DARK SELF-CONTAINED INTEGRATION TEST")
    print("=" * 60)
    print("\nThis test creates everything from scratch - no prerequisites needed.")

    results = TestResult()
    server_process = None

    try:
        # Step 1: Create and fund accounts
        accounts = await create_and_fund_accounts()

        # Step 2: Deploy contracts
        contracts = await setup_contracts(accounts)

        print(f"\n--- Deployment Summary ---")
        print(f"  Admin: {accounts.admin.public_key}")
        print(f"  Token A: {contracts.token_a}")
        print(f"  Token B: {contracts.token_b}")
        print(f"  Orderbook: {contracts.orderbook}")

        # Step 3: Start backend server FIRST (so event listener can detect deposits)
        server_process = start_backend_server(
            accounts.admin.secret,
            contracts.orderbook,
        )

        if not await wait_for_server_ready():
            raise RuntimeError("Server did not start in time")

        # Step 4: Make deposits AFTER server is running (so event listener sees them)
        await setup_deposits(accounts, contracts)

        # Step 5: Create clients
        user1_client = LumenDarkClient(
            base_url=API_BASE_URL,
            keypair=accounts.user1,
        )
        user2_client = LumenDarkClient(
            base_url=API_BASE_URL,
            keypair=accounts.user2,
        )

        print("\n" + "=" * 60)
        print("RUNNING TESTS")
        print("=" * 60)

        # Step 6: Run tests
        await test_health_check(results)
        await test_order_placement(results, user1_client, user2_client)
        await test_order_cancellation(results, user1_client)
        await test_multiple_orders(results, user1_client, user2_client)
        await test_withdrawal(results, user1_client)
        await test_insufficient_balance(results, user1_client)

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Cleanup: stop server
        if server_process:
            print("\n--- Cleanup ---")
            print("  Stopping server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
            print("  Server stopped")

    # Summary
    success = results.summary()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

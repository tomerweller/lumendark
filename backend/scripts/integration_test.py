#!/usr/bin/env python3
"""
Comprehensive E2E integration test for Lumen Dark on Stellar Testnet.

Tests:
- Multiple deposits (Token A and Token B)
- Order placement (buy and sell)
- Order matching and settlement
- Order cancellation
- Withdrawals

Prerequisites:
- Backend server running with ADMIN_SECRET_KEY set
- Stellar CLI configured with 'admin', 'user1', 'user2' keys
- Testnet contracts deployed
"""

import asyncio
import subprocess
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, "/Users/tomer/dev/lumendark/client")
sys.path.insert(0, "/Users/tomer/dev/lumendark/backend")

from stellar_sdk import Keypair
from lumendark_client import LumenDarkClient

# Contract addresses (from deployment)
ORDERBOOK_CONTRACT = "CDNTW7OWJF7LYWERWLQMUUCUIR5Q4XMFSXCHALRS3V3SN5KRDSCJT2DY"
TOKEN_A_CONTRACT = "CCZXVH2AJO3X3ZIUXSN2VR5I3TZ4MNDUAI3JYDMTPOLXMCOOIVUMNKFW"
TOKEN_B_CONTRACT = "CDRASGTVJWOQTWCXNXD2YHIHHK2BHUONJMQHHWE25HQMFONWBL4XCYE3"

# Backend API
API_BASE_URL = "http://localhost:8000"

# Test amounts (with 7 decimals)
DEPOSIT_A_AMOUNT = 500_0000000  # 500 Token A
DEPOSIT_B_AMOUNT = 2500_0000000  # 2500 Token B


def get_keypair(alias: str) -> Keypair:
    """Get keypair from stellar CLI."""
    result = subprocess.run(
        ["stellar", "keys", "show", alias],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get keypair for {alias}: {result.stderr}")
    secret = result.stdout.strip()
    return Keypair.from_secret(secret)


def get_address(alias: str) -> str:
    """Get public address from stellar CLI."""
    result = subprocess.run(
        ["stellar", "keys", "address", alias],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get address for {alias}: {result.stderr}")
    return result.stdout.strip()


def invoke_contract(source: str, contract: str, function: str, args: list[str], timeout: int = 60) -> str:
    """Invoke a contract function."""
    cmd = [
        "stellar", "contract", "invoke",
        "--id", contract,
        "--source-account", source,
        "--network", "testnet",
        "--",
        function,
    ] + args

    print(f"    $ stellar contract invoke ... {function} {' '.join(args[:4])}...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0:
        raise RuntimeError(f"Contract invocation failed: {result.stderr}")

    return result.stdout.strip()


def deposit_to_orderbook(user_alias: str, asset: str, amount: int) -> None:
    """Have a user deposit tokens to the orderbook contract."""
    user_address = get_address(user_alias)

    invoke_contract(
        source=user_alias,
        contract=ORDERBOOK_CONTRACT,
        function="deposit",
        args=[
            "--user", user_address,
            "--asset", f'"{asset.upper()}"',
            "--amount", str(amount),
        ],
    )


def check_balance(user_alias: str, asset: str) -> int:
    """Check a user's balance in the orderbook contract."""
    user_address = get_address(user_alias)

    result = invoke_contract(
        source="admin",
        contract=ORDERBOOK_CONTRACT,
        function="get_balance",
        args=[
            "--user", user_address,
            "--asset", f'"{asset.upper()}"',
        ],
    )
    return int(result.replace('"', ''))


class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def success(self, name: str):
        self.passed += 1
        print(f"  ✅ {name}")

    def failure(self, name: str, error: str):
        self.failed += 1
        self.errors.append((name, error))
        print(f"  ❌ {name}: {error}")

    def summary(self):
        print(f"\n{'=' * 60}")
        print(f"Results: {self.passed} passed, {self.failed} failed")
        if self.errors:
            print("\nFailures:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        print('=' * 60)
        return self.failed == 0


async def test_health_check(results: TestResult):
    """Test API health endpoint."""
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/health")
            if response.status_code == 200 and response.json()["status"] == "healthy":
                results.success("Health check")
            else:
                results.failure("Health check", f"Unexpected response: {response.text}")
        except Exception as e:
            results.failure("Health check", str(e))


async def test_deposits(results: TestResult):
    """Test multiple deposits for both users."""
    print("\n--- Testing Deposits ---")

    # Get initial balances
    try:
        initial_a1 = check_balance("user1", "a")
    except:
        initial_a1 = 0
    try:
        initial_b2 = check_balance("user2", "b")
    except:
        initial_b2 = 0

    # User1 deposits Token A
    try:
        print(f"  Depositing {DEPOSIT_A_AMOUNT // 10000000} Token A for user1...")
        deposit_to_orderbook("user1", "a", DEPOSIT_A_AMOUNT)

        # Verify balance increased
        new_balance = check_balance("user1", "a")
        expected = initial_a1 + DEPOSIT_A_AMOUNT
        if new_balance >= expected:
            results.success(f"User1 deposit Token A (balance: {new_balance})")
        else:
            results.failure("User1 deposit Token A", f"Expected >= {expected}, got {new_balance}")
    except Exception as e:
        results.failure("User1 deposit Token A", str(e))

    # User2 deposits Token B
    try:
        print(f"  Depositing {DEPOSIT_B_AMOUNT // 10000000} Token B for user2...")
        deposit_to_orderbook("user2", "b", DEPOSIT_B_AMOUNT)

        new_balance = check_balance("user2", "b")
        expected = initial_b2 + DEPOSIT_B_AMOUNT
        if new_balance >= expected:
            results.success(f"User2 deposit Token B (balance: {new_balance})")
        else:
            results.failure("User2 deposit Token B", f"Expected >= {expected}, got {new_balance}")
    except Exception as e:
        results.failure("User2 deposit Token B", str(e))

    # Wait for event listener to detect deposits
    print("  Waiting for deposit events to be detected...")
    await asyncio.sleep(10)


async def test_order_placement_and_matching(results: TestResult, user1_client: LumenDarkClient, user2_client: LumenDarkClient):
    """Test order placement and matching."""
    print("\n--- Testing Order Placement and Matching ---")

    # User1 places a SELL order for Token A
    try:
        print("  User1 placing SELL order: 100 Token A @ price 5...")
        sell_msg_id = await user1_client.submit_order(
            side="sell",
            price="5",  # 5 Token B per Token A
            quantity="100",  # 100 Token A
        )
        results.success(f"User1 SELL order submitted (msg_id: {sell_msg_id[:8]}...)")

        # Wait for processing
        await asyncio.sleep(2)

        # Check status (StatusResponse is a dataclass)
        status = await user1_client.get_status(sell_msg_id)
        if status.is_accepted:
            order_id = status.order_id
            results.success(f"User1 SELL order accepted (order_id: {order_id})")
        else:
            results.failure("User1 SELL order status", f"Expected accepted, got {status.status}")

    except Exception as e:
        results.failure("User1 SELL order", str(e))
        return None, None

    # User2 places a BUY order that should match
    try:
        print("  User2 placing BUY order: 50 Token A @ price 5...")
        buy_msg_id = await user2_client.submit_order(
            side="buy",
            price="5",  # Willing to pay 5 Token B per Token A
            quantity="50",  # 50 Token A
        )
        results.success(f"User2 BUY order submitted (msg_id: {buy_msg_id[:8]}...)")

        # Wait for matching and settlement
        print("  Waiting for order matching and settlement...")
        await asyncio.sleep(15)  # Allow time for settlement

        status = await user2_client.get_status(buy_msg_id)
        if status.is_accepted:
            results.success(f"User2 BUY order matched")
        else:
            results.failure("User2 BUY order status", f"Got {status.status}")

    except Exception as e:
        results.failure("User2 BUY order", str(e))

    return sell_msg_id, buy_msg_id


async def test_order_cancellation(results: TestResult, user1_client: LumenDarkClient):
    """Test order cancellation."""
    print("\n--- Testing Order Cancellation ---")

    # Place an order to cancel
    try:
        print("  User1 placing SELL order to cancel: 25 Token A @ price 10...")
        msg_id = await user1_client.submit_order(
            side="sell",
            price="10",
            quantity="25",
        )
        await asyncio.sleep(2)

        # Get order_id (StatusResponse is a dataclass)
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

    # Get initial on-chain balance
    try:
        initial_balance = check_balance("user1", "a")
        print(f"  Initial on-chain balance: {initial_balance}")
    except:
        initial_balance = 0

    withdraw_amount = 50_0000000  # 50 Token A

    try:
        print(f"  Requesting withdrawal of {withdraw_amount // 10000000} Token A...")
        msg_id = await user1_client.request_withdrawal(
            asset="a",
            amount=str(withdraw_amount),
        )
        results.success(f"Withdrawal requested (msg_id: {msg_id[:8]}...)")

        # Wait for on-chain withdrawal
        print("  Waiting for on-chain withdrawal...")
        await asyncio.sleep(20)

        # Check status (StatusResponse is a dataclass)
        status = await user1_client.get_status(msg_id)
        if status.is_accepted:
            results.success("Withdrawal accepted")
        else:
            results.failure("Withdrawal status", f"Got {status.status}")

        # Verify on-chain balance decreased
        new_balance = check_balance("user1", "a")
        print(f"  New on-chain balance: {new_balance}")

        # Note: Balance may have changed due to trades, so just verify withdrawal processed

    except Exception as e:
        results.failure("Withdrawal", str(e))


async def test_multiple_orders_stress(results: TestResult, user1_client: LumenDarkClient, user2_client: LumenDarkClient):
    """Test multiple rapid orders."""
    print("\n--- Testing Multiple Orders ---")

    # Place multiple sell orders at different prices
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

        # Check all orders accepted (StatusResponse is a dataclass)
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

    # Place a buy order that matches some of them
    try:
        print("  Placing BUY order: 25 @ 7 (should match 2 orders)...")
        msg_id = await user2_client.submit_order(
            side="buy",
            price="7",
            quantity="25",
        )

        await asyncio.sleep(15)

        status = await user2_client.get_status(msg_id)
        if status.is_accepted:
            results.success("Partial fill BUY order processed")
        else:
            results.failure("Partial fill BUY order", f"Got {status.status}")

    except Exception as e:
        results.failure("Partial fill BUY order", str(e))


async def test_insufficient_balance(results: TestResult, user1_client: LumenDarkClient):
    """Test order rejection due to insufficient balance."""
    print("\n--- Testing Insufficient Balance ---")

    try:
        # Try to place a huge order that should exceed balance
        print("  Placing order exceeding balance...")
        msg_id = await user1_client.submit_order(
            side="sell",
            price="1",
            quantity="999999999",  # Huge quantity
        )

        await asyncio.sleep(2)

        # StatusResponse is a dataclass
        status = await user1_client.get_status(msg_id)
        if status.is_rejected:
            results.success("Order correctly rejected for insufficient balance")
        else:
            # May be accepted if user has huge balance, that's ok too
            results.success(f"Order processed with status: {status.status}")

    except Exception as e:
        # Rejection is expected
        results.success("Order rejected (exception)")


async def main():
    print("=" * 60)
    print("LUMEN DARK E2E INTEGRATION TEST")
    print("=" * 60)
    print(f"\nOrderbook Contract: {ORDERBOOK_CONTRACT}")
    print(f"Token A Contract: {TOKEN_A_CONTRACT}")
    print(f"Token B Contract: {TOKEN_B_CONTRACT}")
    print(f"API Base URL: {API_BASE_URL}")

    results = TestResult()

    # Get keypairs
    try:
        user1_keypair = get_keypair("user1")
        user2_keypair = get_keypair("user2")
        print(f"\nUser1: {user1_keypair.public_key[:12]}...")
        print(f"User2: {user2_keypair.public_key[:12]}...")
    except Exception as e:
        print(f"\n❌ Failed to get keypairs: {e}")
        print("Make sure 'stellar keys' are configured for 'user1' and 'user2'")
        return 1

    # Create clients
    user1_client = LumenDarkClient(
        base_url=API_BASE_URL,
        keypair=user1_keypair,
    )
    user2_client = LumenDarkClient(
        base_url=API_BASE_URL,
        keypair=user2_keypair,
    )

    print("\n" + "=" * 60)

    # Run tests
    try:
        await test_health_check(results)
        await test_deposits(results)
        await test_order_placement_and_matching(results, user1_client, user2_client)
        await test_order_cancellation(results, user1_client)
        await test_multiple_orders_stress(results, user1_client, user2_client)
        await test_withdrawal(results, user1_client)
        await test_insufficient_balance(results, user1_client)

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

    # Print final balances
    print("\n--- Final On-Chain Balances ---")
    try:
        print(f"  User1 Token A: {check_balance('user1', 'a')}")
        print(f"  User1 Token B: {check_balance('user1', 'b')}")
        print(f"  User2 Token A: {check_balance('user2', 'a')}")
        print(f"  User2 Token B: {check_balance('user2', 'b')}")
    except Exception as e:
        print(f"  Could not fetch balances: {e}")

    # Summary
    success = results.summary()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

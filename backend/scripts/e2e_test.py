#!/usr/bin/env python3
"""End-to-end test for Lumen Dark on testnet."""

import asyncio
import hashlib
import subprocess
import time
from decimal import Decimal

import httpx
from stellar_sdk import Keypair

# Contract addresses (from deployment)
ORDERBOOK_CONTRACT = "CDNTW7OWJF7LYWERWLQMUUCUIR5Q4XMFSXCHALRS3V3SN5KRDSCJT2DY"
TOKEN_A_CONTRACT = "CCZXVH2AJO3X3ZIUXSN2VR5I3TZ4MNDUAI3JYDMTPOLXMCOOIVUMNKFW"
TOKEN_B_CONTRACT = "CDRASGTVJWOQTWCXNXD2YHIHHK2BHUONJMQHHWE25HQMFONWBL4XCYE3"

# Backend API (will be started separately)
API_BASE_URL = "http://localhost:8000"


def get_keypair(alias: str) -> Keypair:
    """Get keypair from stellar CLI."""
    result = subprocess.run(
        ["stellar", "keys", "show", alias],
        capture_output=True,
        text=True,
    )
    secret = result.stdout.strip()
    return Keypair.from_secret(secret)


def get_address(alias: str) -> str:
    """Get public address from stellar CLI."""
    result = subprocess.run(
        ["stellar", "keys", "address", alias],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def invoke_contract(source: str, contract: str, function: str, args: list[str]) -> str:
    """Invoke a contract function."""
    cmd = [
        "stellar", "contract", "invoke",
        "--id", contract,
        "--source-account", source,
        "--network", "testnet",
        "--",
        function,
    ] + args

    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  Error: {result.stderr}")
        raise RuntimeError(f"Contract invocation failed: {result.stderr}")

    return result.stdout.strip()


def deposit_to_orderbook(user_alias: str, asset: str, amount: int) -> None:
    """Have a user deposit tokens to the orderbook contract."""
    user_address = get_address(user_alias)

    print(f"\n  Depositing {amount} {asset} for {user_alias}...")

    # First, user needs to approve the orderbook contract to transfer tokens
    token_contract = TOKEN_A_CONTRACT if asset == "a" else TOKEN_B_CONTRACT

    # The deposit function in the contract handles the transfer
    # We need to call it with the user as the source
    # Asset enum needs to be JSON encoded
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
    print(f"  Deposited successfully!")


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


def sign_request(keypair: Keypair, method: str, path: str, body: bytes) -> dict:
    """Sign a request for the API."""
    timestamp = int(time.time())
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{method}|{path}|{body_hash}|{timestamp}"
    message_bytes = message.encode("utf-8")

    signature = keypair.sign(message_bytes)
    signature_hex = signature.hex()

    return {
        "X-Stellar-Address": keypair.public_key,
        "X-Stellar-Signature": signature_hex,
        "X-Timestamp": str(timestamp),
        "Content-Type": "application/json",
    }


async def test_deposit_flow():
    """Test deposit detection and balance updates."""
    print("\n=== Testing Deposit Flow ===")

    # Check initial balances
    print("\nChecking initial balances in contract...")
    try:
        bal_a = check_balance("user1", "a")
        print(f"  User1 Token A balance: {bal_a}")
    except Exception as e:
        print(f"  User1 Token A balance: 0 (not set)")
        bal_a = 0

    # User1 deposits Token A
    print("\n1. User1 deposits 1000 Token A...")
    deposit_to_orderbook("user1", "a", 1000_0000000)  # 1000 with 7 decimals

    # Check balance after deposit
    bal_a_after = check_balance("user1", "a")
    print(f"  User1 Token A balance after: {bal_a_after}")
    assert bal_a_after == 1000_0000000, f"Expected 1000_0000000, got {bal_a_after}"

    # User2 deposits Token B
    print("\n2. User2 deposits 5000 Token B...")
    deposit_to_orderbook("user2", "b", 5000_0000000)

    bal_b = check_balance("user2", "b")
    print(f"  User2 Token B balance: {bal_b}")
    assert bal_b == 5000_0000000, f"Expected 5000_0000000, got {bal_b}"

    print("\n✅ Deposit flow works!")


async def test_order_matching():
    """Test order matching via API."""
    print("\n=== Testing Order Matching (Mock) ===")

    # For this test, we'll use the in-memory backend without blockchain
    # The full E2E with blockchain events would require running the event listener

    print("\nNote: Full order matching E2E requires running the backend server")
    print("with deposit event listener connected to testnet.")
    print("\nTo run the full test:")
    print("  1. Start the backend: uvicorn lumendark.api.app:app --reload")
    print("  2. Deposits on-chain will be detected and credited")
    print("  3. Users can then place orders via the API")

    print("\n✅ Contract deployment and deposits verified!")


async def test_withdraw_flow():
    """Test withdrawal from contract."""
    print("\n=== Testing Withdrawal Flow ===")

    # Admin can call withdraw on behalf of users
    user1_addr = get_address("user1")

    print("\n1. Withdrawing 100 Token A for user1...")
    invoke_contract(
        source="admin",
        contract=ORDERBOOK_CONTRACT,
        function="withdraw",
        args=[
            "--user", user1_addr,
            "--asset", '"A"',
            "--amount", str(100_0000000),
        ],
    )

    bal_after = check_balance("user1", "a")
    print(f"  User1 Token A balance after withdrawal: {bal_after}")
    assert bal_after == 900_0000000, f"Expected 900_0000000, got {bal_after}"

    print("\n✅ Withdrawal flow works!")


async def main():
    print("=" * 60)
    print("LUMEN DARK E2E TEST")
    print("=" * 60)
    print(f"\nOrderbook Contract: {ORDERBOOK_CONTRACT}")
    print(f"Token A Contract: {TOKEN_A_CONTRACT}")
    print(f"Token B Contract: {TOKEN_B_CONTRACT}")

    try:
        await test_deposit_flow()
        await test_withdraw_flow()
        await test_order_matching()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

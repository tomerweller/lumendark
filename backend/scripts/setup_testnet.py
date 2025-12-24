#!/usr/bin/env python3
"""Set up testnet for E2E testing."""

import asyncio
import subprocess
import time

from stellar_sdk import (
    Keypair,
    Network,
    Server,
    TransactionBuilder,
    Asset,
)

# Testnet configuration
HORIZON_URL = "https://horizon-testnet.stellar.org"
NETWORK_PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE


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


def setup_trustlines():
    """Set up trustlines for test users."""
    server = Server(HORIZON_URL)

    # Get keypairs
    token_issuer = get_keypair("token_issuer")
    user1 = get_keypair("user1")
    user2 = get_keypair("user2")

    issuer_address = get_address("token_issuer")

    # Define assets
    token_a = Asset("TOKA", issuer_address)
    token_b = Asset("TOKB", issuer_address)

    # Add trustlines for user1
    print("Adding trustlines for user1...")
    user1_account = server.load_account(user1.public_key)
    tx = (
        TransactionBuilder(
            source_account=user1_account,
            network_passphrase=NETWORK_PASSPHRASE,
            base_fee=100,
        )
        .append_change_trust_op(asset=token_a)
        .append_change_trust_op(asset=token_b)
        .set_timeout(30)
        .build()
    )
    tx.sign(user1)
    response = server.submit_transaction(tx)
    print(f"  User1 trustlines: {response['successful']}")

    # Add trustlines for user2
    print("Adding trustlines for user2...")
    user2_account = server.load_account(user2.public_key)
    tx = (
        TransactionBuilder(
            source_account=user2_account,
            network_passphrase=NETWORK_PASSPHRASE,
            base_fee=100,
        )
        .append_change_trust_op(asset=token_a)
        .append_change_trust_op(asset=token_b)
        .set_timeout(30)
        .build()
    )
    tx.sign(user2)
    response = server.submit_transaction(tx)
    print(f"  User2 trustlines: {response['successful']}")

    # Mint tokens to users
    print("Minting tokens...")
    issuer_account = server.load_account(issuer_address)

    # User1 gets Token A (will be seller)
    # User2 gets Token B (will be buyer)
    tx = (
        TransactionBuilder(
            source_account=issuer_account,
            network_passphrase=NETWORK_PASSPHRASE,
            base_fee=100,
        )
        .append_payment_op(
            destination=user1.public_key,
            asset=token_a,
            amount="10000",
        )
        .append_payment_op(
            destination=user2.public_key,
            asset=token_b,
            amount="10000",
        )
        .set_timeout(30)
        .build()
    )
    tx.sign(token_issuer)
    response = server.submit_transaction(tx)
    print(f"  Tokens minted: {response['successful']}")

    print("\nSetup complete!")
    print(f"  User1 ({user1.public_key}): 10000 TOKA")
    print(f"  User2 ({user2.public_key}): 10000 TOKB")


if __name__ == "__main__":
    setup_trustlines()

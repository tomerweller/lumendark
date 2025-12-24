"""API integration tests."""

import asyncio
import hashlib
import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from stellar_sdk import Keypair

from lumendark.api.app import create_app
from lumendark.storage.user_store import UserStore
from lumendark.storage.order_book import OrderBook
from lumendark.storage.message_store import MessageStore
from lumendark.queues.message_queue import MessageQueue
from lumendark.queues.action_queue import ActionQueue


def sign_request(
    keypair: Keypair,
    method: str,
    path: str,
    body: bytes,
) -> tuple[str, str, str]:
    """Sign a request for testing."""
    timestamp = int(time.time())
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{method}|{path}|{body_hash}|{timestamp}"
    message_bytes = message.encode("utf-8")

    signature = keypair.sign(message_bytes)
    signature_hex = signature.hex()

    return keypair.public_key, signature_hex, str(timestamp)


@pytest.fixture
def user_keypair() -> Keypair:
    return Keypair.random()


@pytest.fixture
def user_store() -> UserStore:
    return UserStore()


@pytest.fixture
def order_book() -> OrderBook:
    return OrderBook()


@pytest.fixture
def message_store() -> MessageStore:
    return MessageStore()


@pytest.fixture
def message_queue() -> MessageQueue:
    return MessageQueue()


@pytest.fixture
def action_queue() -> ActionQueue:
    return ActionQueue()


@pytest.fixture
def app(
    user_store: UserStore,
    order_book: OrderBook,
    message_store: MessageStore,
    message_queue: MessageQueue,
    action_queue: ActionQueue,
):
    """Create test app without running handlers."""
    return create_app(
        user_store=user_store,
        order_book=order_book,
        message_store=message_store,
        message_queue=message_queue,
        action_queue=action_queue,
        run_handlers=False,
    )


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as client:
        yield client


class TestHealthCheck:
    """Health check endpoint tests."""

    def test_health_check(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestOrderEndpoints:
    """Order API endpoint tests."""

    def test_submit_order_returns_message_id(
        self,
        client: TestClient,
        user_keypair: Keypair,
    ) -> None:
        """Submit order should return message_id."""
        body = b'{"side": "buy", "price": "10.5", "quantity": "100"}'
        address, signature, timestamp = sign_request(
            user_keypair, "POST", "/orders", body
        )

        response = client.post(
            "/orders",
            content=body,
            headers={
                "X-Stellar-Address": address,
                "X-Stellar-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "message_id" in data
        assert len(data["message_id"]) == 36  # UUID format

    def test_submit_order_queues_message(
        self,
        client: TestClient,
        user_keypair: Keypair,
        message_queue: MessageQueue,
        message_store: MessageStore,
    ) -> None:
        """Submit order should add message to queue and store."""
        body = b'{"side": "sell", "price": "20", "quantity": "50"}'
        address, signature, timestamp = sign_request(
            user_keypair, "POST", "/orders", body
        )

        response = client.post(
            "/orders",
            content=body,
            headers={
                "X-Stellar-Address": address,
                "X-Stellar-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        message_id = response.json()["message_id"]

        # Check message is in store
        message = message_store.get(message_id)
        assert message is not None
        assert message.user_address == address
        assert message.payload["side"] == "sell"
        assert message.payload["price"] == "20"
        assert message.payload["quantity"] == "50"

        # Check message is in queue
        assert not message_queue.empty

    def test_submit_order_invalid_side_rejected(
        self,
        client: TestClient,
        user_keypair: Keypair,
    ) -> None:
        """Submit order with invalid side should be rejected."""
        body = b'{"side": "invalid", "price": "10", "quantity": "100"}'
        address, signature, timestamp = sign_request(
            user_keypair, "POST", "/orders", body
        )

        response = client.post(
            "/orders",
            content=body,
            headers={
                "X-Stellar-Address": address,
                "X-Stellar-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 422  # Validation error

    def test_submit_order_without_auth_rejected(
        self,
        client: TestClient,
    ) -> None:
        """Submit order without auth headers should be rejected."""
        response = client.post(
            "/orders",
            json={"side": "buy", "price": "10", "quantity": "100"},
        )

        assert response.status_code == 422  # Missing headers

    def test_submit_order_invalid_signature_rejected(
        self,
        client: TestClient,
        user_keypair: Keypair,
    ) -> None:
        """Submit order with invalid signature should be rejected."""
        body = b'{"side": "buy", "price": "10", "quantity": "100"}'
        address, signature, timestamp = sign_request(
            user_keypair, "POST", "/orders", body
        )

        # Modify signature to make it invalid
        bad_signature = "00" + signature[2:]

        response = client.post(
            "/orders",
            content=body,
            headers={
                "X-Stellar-Address": address,
                "X-Stellar-Signature": bad_signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 401

    def test_cancel_order_returns_message_id(
        self,
        client: TestClient,
        user_keypair: Keypair,
    ) -> None:
        """Cancel order should return message_id."""
        body = b'{"order_id": "some-order-id"}'
        address, signature, timestamp = sign_request(
            user_keypair, "POST", "/orders/cancel", body
        )

        response = client.post(
            "/orders/cancel",
            content=body,
            headers={
                "X-Stellar-Address": address,
                "X-Stellar-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "message_id" in data


class TestWithdrawalEndpoints:
    """Withdrawal API endpoint tests."""

    def test_request_withdrawal_returns_message_id(
        self,
        client: TestClient,
        user_keypair: Keypair,
    ) -> None:
        """Request withdrawal should return message_id."""
        body = b'{"asset": "a", "amount": "100"}'
        address, signature, timestamp = sign_request(
            user_keypair, "POST", "/withdrawals", body
        )

        response = client.post(
            "/withdrawals",
            content=body,
            headers={
                "X-Stellar-Address": address,
                "X-Stellar-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "message_id" in data

    def test_request_withdrawal_invalid_asset_rejected(
        self,
        client: TestClient,
        user_keypair: Keypair,
    ) -> None:
        """Request withdrawal with invalid asset should be rejected."""
        body = b'{"asset": "c", "amount": "100"}'
        address, signature, timestamp = sign_request(
            user_keypair, "POST", "/withdrawals", body
        )

        response = client.post(
            "/withdrawals",
            content=body,
            headers={
                "X-Stellar-Address": address,
                "X-Stellar-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 422


class TestStatusEndpoints:
    """Status API endpoint tests."""

    def test_get_message_status(
        self,
        client: TestClient,
        user_keypair: Keypair,
    ) -> None:
        """Get message status should return current status."""
        # First submit an order
        body = b'{"side": "buy", "price": "10", "quantity": "100"}'
        address, signature, timestamp = sign_request(
            user_keypair, "POST", "/orders", body
        )

        response = client.post(
            "/orders",
            content=body,
            headers={
                "X-Stellar-Address": address,
                "X-Stellar-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        message_id = response.json()["message_id"]

        # Now get status
        status_response = client.get(f"/messages/{message_id}")

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["message_id"] == message_id
        assert data["type"] == "order"
        assert data["status"] == "pending"

    def test_get_message_status_not_found(
        self,
        client: TestClient,
    ) -> None:
        """Get status for unknown message should return 404."""
        response = client.get("/messages/nonexistent-id")
        assert response.status_code == 404

    def test_get_user_balance(
        self,
        client: TestClient,
        user_store: UserStore,
        user_keypair: Keypair,
    ) -> None:
        """Get user balance should return current balances."""
        # Set up some balances
        address = user_keypair.public_key
        user_store.deposit(address, "a", Decimal("1000"))
        user_store.deposit(address, "b", Decimal("500"))
        user_store.allocate(address, "a", Decimal("200"))

        response = client.get(f"/messages/balances/{address}")

        assert response.status_code == 200
        data = response.json()
        assert data["user_address"] == address
        assert data["asset_a_available"] == "800"
        assert data["asset_a_liabilities"] == "200"
        assert data["asset_b_available"] == "500"
        assert data["asset_b_liabilities"] == "0"

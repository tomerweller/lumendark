"""Lumen Dark client for interacting with the dark pool API."""

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx
from stellar_sdk import Keypair

from lumendark_client.exceptions import (
    AuthenticationError,
    NetworkError,
    NotFoundError,
    OrderRejectedError,
    TimeoutError,
)


@dataclass
class StatusResponse:
    """Response from message status query."""

    message_id: str
    type: str
    status: str
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    order_id: Optional[str] = None
    trades_count: Optional[int] = None

    @property
    def is_pending(self) -> bool:
        return self.status in ("pending", "processing")

    @property
    def is_accepted(self) -> bool:
        return self.status == "accepted"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"


@dataclass
class BalanceResponse:
    """Response from balance query."""

    user_address: str
    asset_a_available: str
    asset_a_liabilities: str
    asset_b_available: str
    asset_b_liabilities: str


class LumenDarkClient:
    """
    Client for interacting with Lumen Dark dark pool.

    All requests are signed using the provided Stellar keypair.
    """

    def __init__(
        self,
        base_url: str,
        keypair: Keypair,
        timeout: float = 30.0,
    ) -> None:
        """
        Initialize the client.

        Args:
            base_url: Base URL of the Lumen Dark API
            keypair: Stellar keypair for signing requests
            timeout: Request timeout in seconds
        """
        self._base_url = base_url.rstrip("/")
        self._keypair = keypair
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "LumenDarkClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _sign_request(
        self,
        method: str,
        path: str,
        body: bytes,
    ) -> tuple[str, str, str]:
        """
        Sign a request and return authentication headers.

        Returns:
            Tuple of (address, signature, timestamp)
        """
        timestamp = int(time.time())
        body_hash = hashlib.sha256(body).hexdigest()
        message = f"{method}|{path}|{body_hash}|{timestamp}"
        message_bytes = message.encode("utf-8")

        signature = self._keypair.sign(message_bytes)
        signature_hex = signature.hex()

        return self._keypair.public_key, signature_hex, str(timestamp)

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
    ) -> dict:
        """Make an authenticated request to the API."""
        url = f"{self._base_url}{path}"
        body = b""

        if json is not None:
            import json as json_lib
            body = json_lib.dumps(json).encode("utf-8")

        address, signature, timestamp = self._sign_request(method, path, body)

        headers = {
            "X-Stellar-Address": address,
            "X-Stellar-Signature": signature,
            "X-Timestamp": timestamp,
            "Content-Type": "application/json",
        }

        try:
            if method == "GET":
                response = await self._client.get(url, headers=headers)
            elif method == "POST":
                response = await self._client.post(
                    url,
                    headers=headers,
                    content=body,
                )
            else:
                raise ValueError(f"Unsupported method: {method}")

            if response.status_code == 401:
                raise AuthenticationError(response.text)
            elif response.status_code == 404:
                raise NotFoundError(response.text)
            elif response.status_code >= 400:
                raise NetworkError(f"HTTP {response.status_code}: {response.text}")

            return response.json()

        except httpx.RequestError as e:
            raise NetworkError(f"Request failed: {e}") from e

    async def submit_order(
        self,
        side: str,
        price: str,
        quantity: str,
    ) -> str:
        """
        Submit a new limit order.

        Args:
            side: "buy" or "sell"
            price: Limit price as decimal string
            quantity: Order quantity as decimal string

        Returns:
            Message ID for tracking the order
        """
        response = await self._request(
            "POST",
            "/orders",
            json={
                "side": side,
                "price": price,
                "quantity": quantity,
            },
        )
        return response["message_id"]

    async def cancel_order(self, order_id: str) -> str:
        """
        Cancel an existing order.

        Args:
            order_id: ID of the order to cancel

        Returns:
            Message ID for tracking the cancellation
        """
        response = await self._request(
            "POST",
            "/orders/cancel",
            json={"order_id": order_id},
        )
        return response["message_id"]

    async def request_withdrawal(
        self,
        asset: str,
        amount: str,
    ) -> str:
        """
        Request a withdrawal.

        Args:
            asset: Asset to withdraw ("a" or "b")
            amount: Amount to withdraw as decimal string

        Returns:
            Message ID for tracking the withdrawal
        """
        response = await self._request(
            "POST",
            "/withdrawals",
            json={
                "asset": asset,
                "amount": amount,
            },
        )
        return response["message_id"]

    async def get_status(self, message_id: str) -> StatusResponse:
        """
        Get the status of a message.

        Args:
            message_id: ID of the message to check

        Returns:
            StatusResponse with current status
        """
        response = await self._request("GET", f"/messages/{message_id}")

        created_at = None
        processed_at = None

        if response.get("created_at"):
            created_at = datetime.fromisoformat(
                response["created_at"].replace("Z", "+00:00")
            )
        if response.get("processed_at"):
            processed_at = datetime.fromisoformat(
                response["processed_at"].replace("Z", "+00:00")
            )

        return StatusResponse(
            message_id=response["message_id"],
            type=response["type"],
            status=response["status"],
            rejection_reason=response.get("rejection_reason"),
            created_at=created_at,
            processed_at=processed_at,
            order_id=response.get("order_id"),
            trades_count=response.get("trades_count"),
        )

    async def get_balance(self, user_address: Optional[str] = None) -> BalanceResponse:
        """
        Get a user's balance.

        Args:
            user_address: Address to query (defaults to client's address)

        Returns:
            BalanceResponse with current balances
        """
        address = user_address or self._keypair.public_key
        response = await self._request("GET", f"/messages/balances/{address}")

        return BalanceResponse(
            user_address=response["user_address"],
            asset_a_available=response["asset_a_available"],
            asset_a_liabilities=response["asset_a_liabilities"],
            asset_b_available=response["asset_b_available"],
            asset_b_liabilities=response["asset_b_liabilities"],
        )

    async def wait_for_acceptance(
        self,
        message_id: str,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> StatusResponse:
        """
        Wait for a message to be processed.

        Args:
            message_id: Message ID to wait for
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks

        Returns:
            Final StatusResponse

        Raises:
            TimeoutError: If message is not processed within timeout
            OrderRejectedError: If message is rejected
        """
        start_time = time.time()

        while True:
            status = await self.get_status(message_id)

            if status.is_accepted:
                return status
            elif status.is_rejected:
                raise OrderRejectedError(
                    message_id=message_id,
                    reason=status.rejection_reason or "Unknown reason",
                )

            if time.time() - start_time > timeout:
                raise TimeoutError(message_id)

            await asyncio.sleep(poll_interval)

"""Authentication and signature verification for API requests."""

import hashlib
import hmac
import time
from typing import Optional

from fastapi import HTTPException, Header, Request
from stellar_sdk import Keypair

# Signature validity window (5 minutes)
SIGNATURE_VALIDITY_SECONDS = 300


def verify_stellar_signature(
    public_key: str,
    message: bytes,
    signature: str,
) -> bool:
    """
    Verify a Stellar signature.

    Args:
        public_key: Stellar public key (G...)
        message: Message bytes that were signed
        signature: Base64-encoded signature

    Returns:
        True if signature is valid
    """
    try:
        keypair = Keypair.from_public_key(public_key)
        signature_bytes = bytes.fromhex(signature)
        keypair.verify(message, signature_bytes)
        return True
    except Exception:
        return False


def create_sign_message(
    method: str,
    path: str,
    body: bytes,
    timestamp: int,
) -> bytes:
    """
    Create the message to be signed for API authentication.

    Format: METHOD|PATH|SHA256(BODY)|TIMESTAMP

    Args:
        method: HTTP method (POST, GET, etc.)
        path: Request path
        body: Request body bytes
        timestamp: Unix timestamp

    Returns:
        Message bytes to sign
    """
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{method}|{path}|{body_hash}|{timestamp}"
    return message.encode("utf-8")


async def verify_request_signature(
    request: Request,
    x_stellar_address: str = Header(...),
    x_stellar_signature: str = Header(...),
    x_timestamp: str = Header(...),
) -> str:
    """
    FastAPI dependency to verify request signature.

    Required headers:
    - X-Stellar-Address: User's Stellar public key
    - X-Stellar-Signature: Hex-encoded signature
    - X-Timestamp: Unix timestamp of signature

    Returns:
        Verified user address

    Raises:
        HTTPException 401 if verification fails
    """
    try:
        timestamp = int(x_timestamp)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid timestamp format",
        )

    # Check timestamp is within validity window
    current_time = int(time.time())
    if abs(current_time - timestamp) > SIGNATURE_VALIDITY_SECONDS:
        raise HTTPException(
            status_code=401,
            detail="Timestamp expired or too far in future",
        )

    # Get request body
    body = await request.body()

    # Create message to verify
    message = create_sign_message(
        method=request.method,
        path=request.url.path,
        body=body,
        timestamp=timestamp,
    )

    # Verify signature
    if not verify_stellar_signature(x_stellar_address, message, x_stellar_signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid signature",
        )

    return x_stellar_address

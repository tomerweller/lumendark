"""Exceptions for the Lumen Dark client."""


class LumenDarkError(Exception):
    """Base exception for Lumen Dark client errors."""

    pass


class AuthenticationError(LumenDarkError):
    """Raised when authentication fails."""

    pass


class OrderRejectedError(LumenDarkError):
    """Raised when an order is rejected."""

    def __init__(self, message_id: str, reason: str):
        self.message_id = message_id
        self.reason = reason
        super().__init__(f"Order {message_id} rejected: {reason}")


class TimeoutError(LumenDarkError):
    """Raised when waiting for a message times out."""

    def __init__(self, message_id: str):
        self.message_id = message_id
        super().__init__(f"Timeout waiting for message {message_id}")


class NotFoundError(LumenDarkError):
    """Raised when a resource is not found."""

    pass


class NetworkError(LumenDarkError):
    """Raised when there's a network communication error."""

    pass

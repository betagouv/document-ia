"""Security exceptions for Document IA."""


class SecurityException(Exception):
    """Base exception for all security violations in Document IA."""

    def __init__(self, message: str = "A security violation was detected.") -> None:
        self.message = message
        super().__init__(self.message)


class PathTraversalException(SecurityException, ValueError):
    """Raised when a file path escapes its designated sandbox directory."""

    def __init__(self, message: str = "Path traversal detected.") -> None:
        super().__init__(message)


class BlockedAddressException(SecurityException):
    """Raised when a network address (IP or hostname) is blocked (SSRF prevention)."""

    def __init__(self, message: str = "Network address is blocked.") -> None:
        super().__init__(message)


class DisallowedRedirectException(SecurityException):
    """Raised when an HTTP redirect is attempted during a secured request."""

    def __init__(
        self,
        message: str = "HTTP redirects are disallowed for security reasons.",
    ) -> None:
        super().__init__(message)


class InvalidProtocolException(SecurityException, ValueError):
    """Raised when an unsupported or unsafe protocol scheme is used."""

    def __init__(
        self,
        message: str = "Protocol scheme is invalid or not allowed. Only HTTPS is supported.",
    ) -> None:
        super().__init__(message)


class InvalidUUIDException(SecurityException, ValueError):
    """Raised when an identifier is expected to be a valid UUID but fails validation."""

    def __init__(self, message: str = "Identifier is not a valid UUID.") -> None:
        super().__init__(message)

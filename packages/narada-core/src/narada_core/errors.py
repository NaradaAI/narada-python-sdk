"""Core error classes for Narada SDK."""


class NaradaError(Exception):
    """Base exception for all Narada errors."""

    pass


class NaradaTimeoutError(NaradaError):
    """Raised when a Narada operation times out."""

    pass


class NaradaUnsupportedBrowserError(NaradaError):
    """Raised when an unsupported browser is detected."""

    pass


class NaradaExtensionMissingError(NaradaError):
    """Raised when the Narada browser extension is not installed."""

    pass


class NaradaExtensionUnauthenticatedError(NaradaError):
    """Raised when the Narada browser extension is not authenticated."""

    pass


class NaradaInitializationError(NaradaError):
    """Raised when Narada fails to initialize properly."""

    pass

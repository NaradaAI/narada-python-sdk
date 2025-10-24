class NaradaError(Exception):
    pass


class NaradaTimeoutError(NaradaError):
    pass


class NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(NaradaTimeoutError):
    """Internal helper type to create a `NaradaTimeoutError` with a more helpful message."""

    def __init__(self, timeout: int) -> None:
        super().__init__(
            f"Request timed out after {timeout} seconds. "
            "Try specifying a larger `timeout` value when calling `agent`."
        )


class NaradaUnsupportedBrowserError(NaradaError):
    pass


class NaradaExtensionMissingError(NaradaError):
    pass


class NaradaExtensionUnauthenticatedError(NaradaError):
    pass


class NaradaInitializationError(NaradaError):
    pass

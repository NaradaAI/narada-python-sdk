class NaradaError(Exception):
    pass


class NaradaTimeoutError(NaradaError):
    pass


class NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(NaradaTimeoutError):
    """Internal helper type to create a `NaradaTimeoutError` with a more helpful message."""

    def __init__(self, timeout: int) -> None:
        super().__init__(
            f"Request timed out after {timeout} seconds. "
            "Try specifying a larger `timeout` value when calling `Agent.run`."
        )


class NaradaOperatorMaxStepsExceededError(NaradaError):
    def __init__(
        self,
        message: str,
        *,
        max_operator_steps: int | None = None,
    ) -> None:
        super().__init__(message)
        self.max_operator_steps = max_operator_steps


class NaradaUnsupportedBrowserError(NaradaError):
    pass


class NaradaExtensionMissingError(NaradaError):
    pass


class NaradaExtensionUnauthenticatedError(NaradaError):
    pass


class NaradaInitializationError(NaradaError):
    pass


class UserAbortedError(Exception):
    pass

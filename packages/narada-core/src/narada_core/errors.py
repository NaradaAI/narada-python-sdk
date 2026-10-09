_QUOTA_EXCEEDED_ERROR_CODE = 0


class NaradaError(Exception):
    pass


class NaradaQuotaExceededError(NaradaError):
    def __init__(self) -> None:
        super().__init__(
            "You have run out of credits. Please upgrade your account to continue."
        )


def is_quota_exceeded_error_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    detail = payload.get("detail")
    return isinstance(detail, dict) and detail.get("code") == _QUOTA_EXCEEDED_ERROR_CODE


class NaradaTimeoutError(NaradaError):
    pass


class NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(NaradaTimeoutError):
    """Internal helper type to create a `NaradaTimeoutError` with a more helpful message."""

    def __init__(self, timeout: int) -> None:
        super().__init__(
            f"Request timed out after {timeout} seconds. "
            "Try specifying a larger `timeout` value when calling `Agent.run`."
        )


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

import asyncio
import time
from http import HTTPStatus
from typing import Any

from pyodide.http import pyfetch

__all__ = ["pyfetch_with_retries"]

_PYFETCH_RETRY_ATTEMPTS = 3
_PYFETCH_INITIAL_BACKOFF_SECONDS = 0.5
_PYFETCH_BACKOFF_MULTIPLIER = 2.0
_PYFETCH_RETRYABLE_STATUSES = frozenset(
    status.value
    for status in (
        HTTPStatus.REQUEST_TIMEOUT,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    )
)


def _abort_signal_aborted(signal: Any) -> bool:
    if signal is None:
        return False

    try:
        return bool(getattr(signal, "aborted", False))
    except Exception:
        return False


async def _sleep_before_pyfetch_retry(
    backoff_seconds: float, retry_deadline: float | None
) -> bool:
    if retry_deadline is None:
        await asyncio.sleep(backoff_seconds)
        return True

    remaining_seconds = retry_deadline - time.monotonic()
    if remaining_seconds <= backoff_seconds:
        return False

    await asyncio.sleep(backoff_seconds)
    return time.monotonic() < retry_deadline


async def pyfetch_with_retries(
    url: str,
    *,
    max_attempts: int = _PYFETCH_RETRY_ATTEMPTS,
    initial_backoff_seconds: float = _PYFETCH_INITIAL_BACKOFF_SECONDS,
    backoff_multiplier: float = _PYFETCH_BACKOFF_MULTIPLIER,
    retry_statuses: frozenset[int] | None = _PYFETCH_RETRYABLE_STATUSES,
    retry_deadline: float | None = None,
    **kwargs: Any,
) -> Any:
    """Retries transient pyfetch exceptions with exponential backoff.

    HTTP responses are returned as-is once attempts are exhausted so each caller
    can preserve its existing status-specific handling.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    backoff_seconds = initial_backoff_seconds
    signal = kwargs.get("signal")
    for attempt in range(max_attempts):
        if retry_deadline is not None and time.monotonic() >= retry_deadline:
            raise asyncio.TimeoutError

        try:
            response = await pyfetch(url, **kwargs)
        except Exception:
            if (
                attempt == max_attempts - 1
                or _abort_signal_aborted(signal)
                or (retry_deadline is not None and time.monotonic() >= retry_deadline)
            ):
                raise

            if not await _sleep_before_pyfetch_retry(backoff_seconds, retry_deadline):
                raise
            backoff_seconds *= backoff_multiplier
            continue

        if (
            retry_statuses
            and response.status in retry_statuses
            and attempt < max_attempts - 1
            and not _abort_signal_aborted(signal)
            and (retry_deadline is None or time.monotonic() < retry_deadline)
        ):
            if await _sleep_before_pyfetch_retry(backoff_seconds, retry_deadline):
                backoff_seconds *= backoff_multiplier
                continue

        return response

    raise AssertionError("unreachable")

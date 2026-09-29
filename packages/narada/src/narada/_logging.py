"""Logging support for the Narada SDK.

SDK modules log through ``logging.getLogger(__name__)``, so every record belongs to the
``narada`` logger hierarchy and names the module that emitted it. As the standard library
recommends for libraries, the SDK installs no handlers and leaves levels and propagation to the
application: records reach whatever handlers the application configures, and without any
configuration Python prints warnings and errors to stderr.

High-level SDK steps also log how long they took at DEBUG level through ``log_duration``.
"""

from __future__ import annotations

import logging
import time
from types import TracebackType

LOG_FORMAT = "[%(name)s.%(funcName)s:%(lineno)d] %(message)s"
"""Renders records as ``[narada.<module>.<function>:<line>] <message>``."""

_LOGGER_NAME = "narada"
_HANDLER_NAME = "narada.enable_logging"


def enable_logging(level: int | str = logging.INFO) -> logging.Handler:
    """Prints Narada SDK logs at ``level`` and above to stderr using ``LOG_FORMAT``.

    This is a convenience for scripts and debugging. Applications that configure logging
    themselves already receive Narada records through their own handlers and can use
    ``narada.LOG_FORMAT`` in those handlers' formatters instead.

    Calling this again replaces the handler installed by the previous call. Records still
    propagate to the root logger, so an application with its own root handlers also receives them
    there.

    Returns the installed handler; pass it to ``logging.getLogger("narada").removeHandler`` to
    stop printing.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    for existing in list(logger.handlers):
        if existing.get_name() == _HANDLER_NAME:
            logger.removeHandler(existing)
            existing.close()

    handler = logging.StreamHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(level)
    return handler


class _Duration:
    def __init__(
        self,
        logger: logging.Logger,
        action: str,
        phase: str,
        fields: dict[str, object],
    ) -> None:
        self._logger = logger
        self._action = action
        self._phase = phase
        self._fields = fields
        self._start = 0.0

    def __enter__(self) -> None:
        self._start = time.perf_counter()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._logger.isEnabledFor(logging.DEBUG):
            return

        elapsed_ms = round((time.perf_counter() - self._start) * 1000)
        outcome = "ok" if exc_type is None else exc_type.__name__
        fields = "".join(f" {key}={value}" for key, value in self._fields.items())
        self._logger.debug(
            "Time profile: action=%s phase=%s%s outcome=%s elapsed_ms=%d",
            self._action,
            self._phase,
            fields,
            outcome,
            elapsed_ms,
            # Attribute the record to the function containing the ``with`` statement.
            stacklevel=2,
            extra={
                "narada_time_profile": {
                    "action": self._action,
                    "phase": self._phase,
                    **self._fields,
                    "outcome": outcome,
                    "elapsed_ms": elapsed_ms,
                }
            },
        )


def log_duration(
    logger: logging.Logger, action: str, phase: str, **fields: object
) -> _Duration:
    """Times the enclosed block and logs the result to ``logger`` at DEBUG level.

    The message reads ``Time profile: action=<action> phase=<phase> [<key>=<value> ...]
    outcome=<outcome> elapsed_ms=<ms>``, where ``action`` names a high-level SDK operation, such as
    ``start``, and ``phase`` names a step within it. ``outcome`` is ``ok``, or the name of the
    exception that left the block. The same values are attached to the record as the
    ``narada_time_profile`` attribute for structured log handlers.
    """
    return _Duration(logger, action, phase, fields)

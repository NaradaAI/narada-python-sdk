"""Logging support for the Narada SDK.

SDK modules log through ``logging.getLogger(__name__)``, so every record belongs to the
``narada`` logger hierarchy and names the module that emitted it. As the standard library
recommends for libraries, the SDK installs no handlers and leaves levels and propagation to the
application: records reach whatever handlers the application configures, and without any
configuration Python prints warnings and errors to stderr.
"""

from __future__ import annotations

import logging

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

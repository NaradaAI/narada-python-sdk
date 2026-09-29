from __future__ import annotations

import logging

_LOGGER_NAME = "narada"
_HANDLER_NAME = "narada-sdk"
_LOG_FORMAT = "[narada.%(module)s.%(funcName)s:%(lineno)d] %(message)s"


def _configure_package_logger() -> None:
    package_logger = logging.getLogger(_LOGGER_NAME)
    if any(handler.get_name() == _HANDLER_NAME for handler in package_logger.handlers):
        return

    handler = logging.StreamHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    package_logger.addHandler(handler)
    package_logger.setLevel(logging.WARNING)
    package_logger.propagate = False


def get_logger(module_name: str) -> logging.Logger:
    _configure_package_logger()
    return logging.getLogger(module_name)

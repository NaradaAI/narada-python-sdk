from __future__ import annotations

import inspect
import logging
from io import StringIO

from narada._logger import get_logger

_HANDLER_NAME = "narada-sdk"


def _narada_handler() -> logging.StreamHandler:
    package_logger = logging.getLogger("narada")
    handler = next(
        handler
        for handler in package_logger.handlers
        if handler.get_name() == _HANDLER_NAME
    )
    assert isinstance(handler, logging.StreamHandler)
    return handler


def _emit_log(logger: logging.Logger, level: str, message: str) -> int:
    frame = inspect.currentframe()
    assert frame is not None
    line_number = frame.f_lineno + 1
    getattr(logger, level)("Message: %s", message)
    return line_number


def test_logger_formats_each_level_with_the_call_site() -> None:
    logger = get_logger("narada.test_logger")
    package_logger = logging.getLogger("narada")
    handler = _narada_handler()
    output = StringIO()
    original_stream = handler.setStream(output)
    original_level = package_logger.level

    try:
        package_logger.setLevel(logging.DEBUG)
        expected_lines = {
            level: _emit_log(logger, level, level)
            for level in ("debug", "info", "warning", "error")
        }
    finally:
        package_logger.setLevel(original_level)
        handler.setStream(original_stream)

    assert output.getvalue().splitlines() == [
        f"[narada.test_logger._emit_log:{expected_lines[level]}] Message: {level}"
        for level in ("debug", "info", "warning", "error")
    ]


def test_logger_configuration_is_idempotent_and_does_not_propagate() -> None:
    package_logger = logging.getLogger("narada")
    package_handler = _narada_handler()
    package_output = StringIO()
    original_stream = package_handler.setStream(package_output)
    root_logger = logging.getLogger()
    root_output = StringIO()
    root_handler = logging.StreamHandler(root_output)
    root_logger.addHandler(root_handler)

    try:
        first_logger = get_logger("narada.test_logger")
        second_logger = get_logger("narada.test_logger")
        first_logger.warning("Only once")
    finally:
        root_logger.removeHandler(root_handler)
        package_handler.setStream(original_stream)

    assert first_logger is second_logger
    assert (
        sum(handler.get_name() == _HANDLER_NAME for handler in package_logger.handlers)
        == 1
    )
    assert package_logger.propagate is False
    assert package_output.getvalue().count("Only once") == 1
    assert root_output.getvalue() == ""


def test_logger_exception_includes_traceback() -> None:
    logger = get_logger("narada.test_logger")
    handler = _narada_handler()
    output = StringIO()
    original_stream = handler.setStream(output)

    try:
        try:
            raise ValueError("broken")
        except ValueError:
            logger.exception("Operation failed")
    finally:
        handler.setStream(original_stream)

    log_output = output.getvalue()
    assert "[narada.test_logger.test_logger_exception_includes_traceback:" in log_output
    assert "] Operation failed" in log_output
    assert "Traceback (most recent call last):" in log_output
    assert "ValueError: broken" in log_output

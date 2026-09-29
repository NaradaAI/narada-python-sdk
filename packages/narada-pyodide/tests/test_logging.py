from __future__ import annotations

import inspect
import logging
import sys
from collections.abc import Iterator
from io import StringIO
from types import ModuleType

import pytest


@pytest.fixture(autouse=True)
def restore_narada_logger() -> Iterator[None]:
    logger = logging.getLogger("narada")
    handlers = list(logger.handlers)
    level = logger.level
    propagate = logger.propagate
    yield
    for handler in logger.handlers:
        if handler not in handlers:
            handler.close()
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def _emit_trace_event_to_unavailable_worker(monkeypatch: pytest.MonkeyPatch) -> int:
    """Emits a trace event whose forwarding fails and returns the line that logs the failure."""
    trace_module = sys.modules["narada._trace"]

    def unavailable(event_json: str) -> None:
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(
        trace_module, "_narada_emit_trace_event", unavailable, raising=False
    )
    trace_module.emit_trace_event({"type": "test"})

    lines, start = inspect.getsourcelines(trace_module.emit_trace_event)
    [offset] = [
        index
        for index, line in enumerate(lines)
        if "trace event emission failed" in line
    ]
    return start + offset


def test_importing_narada_leaves_logging_configuration_to_the_application(
    pyodide_narada: ModuleType,
) -> None:
    logger = logging.getLogger("narada")

    assert logger.handlers == []
    assert logger.level == logging.NOTSET
    assert logger.propagate is True


def test_sdk_logs_reach_application_handlers_with_their_call_site(
    pyodide_narada: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        _emit_trace_event_to_unavailable_worker(monkeypatch)

    [record] = caplog.records
    assert record.name == "narada._trace"
    assert record.funcName == "emit_trace_event"
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "trace event emission failed"
    assert record.exc_info is not None


def test_enable_logging_prints_the_narada_format_and_still_propagates(
    pyodide_narada: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    output = StringIO()
    pyodide_narada.enable_logging().setStream(output)

    with caplog.at_level(logging.WARNING):
        line = _emit_trace_event_to_unavailable_worker(monkeypatch)

    first_line, *traceback_lines = output.getvalue().splitlines()
    assert first_line == (
        f"[narada._trace.emit_trace_event:{line}] trace event emission failed"
    )
    assert traceback_lines[0] == "Traceback (most recent call last):"
    assert traceback_lines[-1] == "RuntimeError: worker unavailable"
    assert len(caplog.records) == 1


def test_enable_logging_sets_the_level_and_replaces_its_previous_handler(
    pyodide_narada: ModuleType,
) -> None:
    logger = logging.getLogger("narada")
    application_handler = logging.NullHandler()
    logger.addHandler(application_handler)

    pyodide_narada.enable_logging(logging.WARNING)
    handler = pyodide_narada.enable_logging(logging.DEBUG)

    assert logger.handlers == [application_handler, handler]
    assert logger.level == logging.DEBUG
    assert logger.propagate is True

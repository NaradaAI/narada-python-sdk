from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterator
from io import StringIO
from typing import Any

import aiohttp
import narada
import pytest
from narada import environment as environment_module


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


def _line_of(function: Callable[..., Any], text: str) -> int:
    lines, start = inspect.getsourcelines(function)
    [offset] = [index for index, line in enumerate(lines) if text in line]
    return start + offset


async def _stop_session_with_unreachable_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(*args: object, **kwargs: object) -> aiohttp.ClientSession:
        raise aiohttp.ClientError("connection refused")

    monkeypatch.setattr(aiohttp, "ClientSession", unreachable)
    await environment_module._stop_cloud_browser_session(
        base_url="https://api.narada.test",
        auth_headers={},
        session_id="session-id",
    )


def test_importing_narada_leaves_logging_configuration_to_the_application() -> None:
    logger = logging.getLogger("narada")

    assert logger.handlers == []
    assert logger.level == logging.NOTSET
    assert logger.propagate is True


@pytest.mark.asyncio
async def test_sdk_logs_reach_application_handlers_with_their_call_site(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        await _stop_session_with_unreachable_backend(monkeypatch)

    [record] = caplog.records
    assert record.name == "narada.environment"
    assert record.funcName == "_stop_cloud_browser_session"
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        "Error calling stop session endpoint: connection refused"
    )


@pytest.mark.asyncio
async def test_enable_logging_prints_the_narada_format_and_still_propagates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    output = StringIO()
    narada.enable_logging().setStream(output)

    with caplog.at_level(logging.WARNING):
        await _stop_session_with_unreachable_backend(monkeypatch)

    line = _line_of(
        environment_module._stop_cloud_browser_session,
        "Error calling stop session endpoint",
    )
    assert output.getvalue() == (
        f"[narada.environment._stop_cloud_browser_session:{line}] "
        "Error calling stop session endpoint: connection refused\n"
    )
    assert len(caplog.records) == 1


def test_enable_logging_sets_the_level_and_replaces_its_previous_handler() -> None:
    logger = logging.getLogger("narada")
    application_handler = logging.NullHandler()
    logger.addHandler(application_handler)

    narada.enable_logging(logging.WARNING)
    handler = narada.enable_logging(logging.DEBUG)

    assert logger.handlers == [application_handler, handler]
    assert logger.level == logging.DEBUG
    assert logger.propagate is True

from __future__ import annotations

import logging
from typing import Any

import pytest
from narada import LambdaEnvironment, RemoteBrowserEnvironment
from narada import _logging as logging_module
from narada import environment as environment_module
from narada._logging import log_duration

logger = logging.getLogger("narada.test_time_profiling")


class _FakeResponse:
    ok = True
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def raise_for_status(self) -> None:
        pass

    async def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClientSession:
    async def __aenter__(self) -> _FakeClientSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def post(self, url: str, **kwargs: object) -> _FakeResponse:
        if url.endswith("/cloud-browser/create-and-initialize-cloud-browser-session"):
            return _FakeResponse({"browser_window_id": "bw-1", "session_id": "s-1"})
        if url.endswith("/cloud-browser/stop-cloud-browser-session"):
            return _FakeResponse({"success": True})
        if url.endswith("/remote-dispatch"):
            return _FakeResponse({"requestId": "req-123"})
        if url.endswith("/extension-actions"):
            return _FakeResponse({"status": "success", "data": None})
        raise AssertionError(f"Unexpected POST URL: {url}")

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        if url.endswith("/sdk/config"):
            return _FakeResponse(
                {"packages": {"narada": {"min_required_version": "0.0.1"}}}
            )
        if url.endswith("/remote-dispatch/responses/req-123"):
            return _FakeResponse(
                {
                    "status": "success",
                    "response": None,
                    "usage": {"actions": 1, "credits": 1},
                    "createdAt": "2026-01-01T00:00:00Z",
                    "completedAt": "2026-01-01T00:00:01Z",
                    "hitlInputMetadata": None,
                }
            )
        raise AssertionError(f"Unexpected GET URL: {url}")


def _time_profiles(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        record.narada_time_profile
        for record in caplog.records
        if hasattr(record, "narada_time_profile")
    ]


def test_log_duration_logs_the_phase_at_the_with_statement(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        logging_module.time, "perf_counter", iter([10.0, 10.25]).__next__
    )

    def connect() -> None:
        with log_duration(logger, "start", "connect_cdp", attempt=2):
            pass

    with caplog.at_level(logging.DEBUG, logger="narada"):
        connect()

    [record] = caplog.records
    assert record.levelno == logging.DEBUG
    assert record.funcName == "connect"
    assert record.lineno == connect.__code__.co_firstlineno + 1
    assert record.getMessage() == (
        "Time profile: action=start phase=connect_cdp attempt=2 outcome=ok "
        "elapsed_ms=250"
    )
    assert _time_profiles(caplog) == [
        {
            "action": "start",
            "phase": "connect_cdp",
            "attempt": 2,
            "outcome": "ok",
            "elapsed_ms": 250,
        }
    ]


def test_log_duration_reports_the_exception_that_left_the_block(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="narada"),
        pytest.raises(TimeoutError),
    ):
        with log_duration(logger, "start", "wait_for_browser_window_id"):
            raise TimeoutError

    [profile] = _time_profiles(caplog)
    assert profile["outcome"] == "TimeoutError"


def test_log_duration_is_silent_unless_debug_is_enabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="narada"):
        with log_duration(logger, "start", "launch_chrome"):
            pass

    assert caplog.records == []


def _logged_phases(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
    """Returns each record's function and message up to its outcome and duration."""
    return [
        (record.funcName, record.getMessage().split(" outcome=")[0])
        for record in caplog.records
    ]


@pytest.mark.asyncio
async def test_environment_lifecycle_logs_time_profiles(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(environment_module.aiohttp, "ClientSession", _FakeClientSession)
    env = LambdaEnvironment(api_key="test-key")

    with caplog.at_level(logging.DEBUG, logger="narada"):
        await env._dispatch_request(prompt="Summarize", timeout=5)
        await env.close()

    assert _logged_phases(caplog) == [
        (
            "_ensure_initialized",
            "Time profile: action=start phase=validate_sdk_config",
        ),
        ("_initialize", "Time profile: action=start phase=create_session"),
        (
            "_ensure_initialized",
            "Time profile: action=start phase=total environment=LambdaEnvironment",
        ),
        ("_dispatch_request", "Time profile: action=agent_run phase=submit"),
        (
            "_dispatch_request",
            "Time profile: action=agent_run phase=wait_for_completion "
            "request_id=req-123",
        ),
        (
            "close",
            "Time profile: action=close phase=total environment=LambdaEnvironment",
        ),
    ]
    assert {profile["outcome"] for profile in _time_profiles(caplog)} == {"ok"}


@pytest.mark.asyncio
async def test_extension_actions_log_time_profiles(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(environment_module.aiohttp, "ClientSession", _FakeClientSession)
    env = RemoteBrowserEnvironment(browser_window_id="bw-1", api_key="test-key")

    with caplog.at_level(logging.DEBUG, logger="narada"):
        await env.close()

    assert _logged_phases(caplog) == [
        (
            "_run_extension_action",
            "Time profile: action=extension_action phase=close_window",
        ),
        (
            "close",
            "Time profile: action=close phase=total "
            "environment=RemoteBrowserEnvironment",
        ),
    ]

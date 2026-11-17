from __future__ import annotations

import logging
import sys
from types import ModuleType
from typing import Any

import pytest


class _FakeResponse:
    ok = True
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


async def _fake_pyfetch(url: str, **kwargs: object) -> _FakeResponse:
    if url.endswith("/sdk/config"):
        return _FakeResponse(
            {"packages": {"narada-pyodide": {"min_required_version": "0.0.1"}}}
        )
    if url.endswith("/cloud-browser/create-and-initialize-cloud-browser-session"):
        return _FakeResponse({"browser_window_id": "bw-1", "session_id": "s-1"})
    if url.endswith("/cloud-browser/stop-cloud-browser-session"):
        return _FakeResponse({"success": True})
    if url.endswith("/remote-dispatch"):
        return _FakeResponse({"requestId": "req-123"})
    if url.endswith("/remote-dispatch/responses/req-123"):
        return _FakeResponse(
            {
                "status": "success",
                "completedAt": "2026-01-01T00:00:01Z",
                "response": None,
                "hitlInputMetadata": None,
            }
        )
    if url.endswith("/extension-actions"):
        return _FakeResponse({"status": "success", "data": None})
    raise AssertionError(f"Unexpected URL: {url}")


@pytest.fixture
def narada_with_fake_backend(
    pyodide_narada: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> ModuleType:
    sys.modules["pyodide.http"].pyfetch.side_effect = _fake_pyfetch
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        lambda event_json: None,
        raising=False,
    )
    monkeypatch.setenv("NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", "req-parent")
    return pyodide_narada


def _logged_phases(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
    """Returns each record's function and message up to its outcome and duration."""
    return [
        (record.funcName, record.getMessage().split(" outcome=")[0])
        for record in caplog.records
    ]


def test_log_duration_reports_the_exception_that_left_the_block(
    pyodide_narada: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    log_duration = sys.modules["narada._logging"].log_duration
    logger = logging.getLogger("narada.test_time_profiling")

    with (
        caplog.at_level(logging.DEBUG, logger="narada"),
        pytest.raises(TimeoutError),
    ):
        with log_duration(logger, "start", "create_session", attempt=1):
            raise TimeoutError

    [record] = caplog.records
    assert (
        record.funcName == "test_log_duration_reports_the_exception_that_left_the_block"
    )
    assert record.getMessage().startswith(
        "Time profile: action=start phase=create_session attempt=1 "
        "outcome=TimeoutError elapsed_ms="
    )


@pytest.mark.asyncio
async def test_environment_lifecycle_logs_time_profiles(
    narada_with_fake_backend: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    env = narada_with_fake_backend.LambdaEnvironment(api_key="test-key")

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


@pytest.mark.asyncio
async def test_extension_actions_log_time_profiles(
    narada_with_fake_backend: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    env = narada_with_fake_backend.RemoteBrowserEnvironment(
        browser_window_id="bw-1", api_key="test-key"
    )

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

from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from packaging.version import InvalidVersion

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PYODIDE_SRC = PROJECT_ROOT / "packages" / "narada-pyodide" / "src"
CORE_SRC = PROJECT_ROOT / "packages" / "narada-core" / "src"


class _FakeResponse:
    def __init__(
        self,
        *,
        ok: bool = True,
        status: int = 200,
        json_data: object | None = None,
        text_data: str = "",
    ) -> None:
        self.ok = ok
        self.status = status
        self._json_data = json_data
        self._text_data = text_data

    async def json(self) -> object | None:
        return self._json_data

    async def text(self) -> str:
        return self._text_data


class _FakeJsProxy:
    def __init__(self, value: object):
        self._value = value

    def to_py(self) -> object:
        return self._value


def _clear_modules() -> None:
    for name in list(sys.modules):
        if name == "narada" or name.startswith("narada."):
            sys.modules.pop(name, None)
    for name in ("js", "pyodide", "pyodide.http", "pyodide.ffi"):
        sys.modules.pop(name, None)


def _import_pyodide_narada(monkeypatch: pytest.MonkeyPatch, *, pyfetch: AsyncMock):
    _clear_modules()
    monkeypatch.syspath_prepend(str(CORE_SRC))
    monkeypatch.syspath_prepend(str(PYODIDE_SRC))

    js_module = ModuleType("js")

    class _AbortController:
        @staticmethod
        def new() -> SimpleNamespace:
            return SimpleNamespace(signal=object(), abort=lambda: None)

    js_module.AbortController = _AbortController
    js_module.setTimeout = lambda callback, timeout: None

    pyodide_module = ModuleType("pyodide")
    pyodide_module.__path__ = []
    pyodide_http_module = ModuleType("pyodide.http")
    pyodide_http_module.pyfetch = pyfetch
    pyodide_ffi_module = ModuleType("pyodide.ffi")
    pyodide_ffi_module.JsProxy = _FakeJsProxy
    pyodide_ffi_module.create_once_callable = lambda fn: fn

    monkeypatch.setitem(sys.modules, "js", js_module)
    monkeypatch.setitem(sys.modules, "pyodide", pyodide_module)
    monkeypatch.setitem(sys.modules, "pyodide.http", pyodide_http_module)
    monkeypatch.setitem(sys.modules, "pyodide.ffi", pyodide_ffi_module)

    import importlib

    narada_pkg = importlib.import_module("narada")
    client_module = importlib.import_module("narada.client")
    window_module = importlib.import_module("narada.window")
    window_module._narada_parent_run_ids = _FakeJsProxy([])
    window_module._narada_request_id = None
    monkeypatch.setattr(builtins, "_narada_request_id", None, raising=False)
    window_module._narada_get_id_token = AsyncMock(return_value="frontend-id-token")
    return narada_pkg, client_module, window_module


@pytest.mark.asyncio
async def test_open_and_initialize_cloud_browser_window_maps_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", "request-maps-123"
    )
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "session_id": "session-123",
                "session_name": "demo",
                "browser_window_id": "browser-window-123",
            }
        )
    )
    narada_pkg, _, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    client = narada_pkg.Narada(api_key="test-api-key")
    window = await client.open_and_initialize_cloud_browser_window(
        session_name="demo",
        session_timeout=321,
        require_extension=False,
    )

    assert isinstance(window, narada_pkg.CloudBrowserWindow)
    assert window.browser_window_id == "browser-window-123"
    assert window.cloud_browser_session_id == "session-123"

    call = pyfetch.await_args
    assert call is not None
    assert call.args[0].endswith(
        "/cloud-browser/create-and-initialize-cloud-browser-session"
    )
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "x-api-key": "test-api-key",
    }
    assert json.loads(call.kwargs["body"]) == {
        "session_name": "demo",
        "session_timeout": 321,
        "require_extension": False,
        "initiator_remote_dispatch_request_id": "request-maps-123",
    }


@pytest.mark.asyncio
async def test_open_and_initialize_cloud_browser_window_requires_initiator_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", raising=False)
    pyfetch = AsyncMock()
    narada_pkg, _, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    client = narada_pkg.Narada(api_key="test-api-key")
    with pytest.raises(ValueError, match="NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID"):
        await client.open_and_initialize_cloud_browser_window()

    pyfetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_and_initialize_cloud_browser_window_includes_initiator_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", " request-local-123 "
    )
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "session_id": "session-123",
                "session_name": "demo",
                "browser_window_id": "browser-window-123",
            }
        )
    )
    narada_pkg, _, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    client = narada_pkg.Narada(api_key="test-api-key")
    await client.open_and_initialize_cloud_browser_window()

    call = pyfetch.await_args
    assert call is not None
    assert json.loads(call.kwargs["body"]) == {
        "session_name": None,
        "session_timeout": None,
        "require_extension": True,
        "initiator_remote_dispatch_request_id": "request-local-123",
    }


@pytest.mark.asyncio
async def test_open_and_initialize_cloud_browser_window_supports_frontend_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NARADA_API_KEY", raising=False)
    monkeypatch.setenv("NARADA_USER_ID", "user-123")
    monkeypatch.setenv("NARADA_ENV", "dev")
    monkeypatch.setenv(
        "NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", "request-bearer-123"
    )

    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(
                json_data={
                    "packages": {"narada-pyodide": {"min_required_version": "0.0.1"}}
                }
            ),
            _FakeResponse(
                json_data={
                    "session_id": "session-456",
                    "session_name": "demo",
                    "browser_window_id": "browser-window-456",
                }
            ),
            _FakeResponse(json_data={"success": True}),
        ]
    )
    narada_pkg, _, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    async with narada_pkg.Narada() as client:
        window = await client.open_and_initialize_cloud_browser_window(
            session_name="demo",
            session_timeout=321,
            require_extension=True,
        )

    assert isinstance(window, narada_pkg.CloudBrowserWindow)
    assert window.browser_window_id == "browser-window-456"
    assert window.cloud_browser_session_id == "session-456"

    sdk_config_call, create_call = pyfetch.await_args_list
    assert sdk_config_call.args[0].endswith("/sdk/config")
    assert sdk_config_call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer frontend-id-token",
        "X-Narada-User-ID": "user-123",
        "X-Narada-Env": "dev",
    }
    assert create_call.args[0].endswith(
        "/cloud-browser/create-and-initialize-cloud-browser-session"
    )
    assert create_call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer frontend-id-token",
        "X-Narada-User-ID": "user-123",
        "X-Narada-Env": "dev",
    }

    await window.close()
    stop_call = pyfetch.await_args_list[-1]
    assert stop_call.args[0].endswith("/cloud-browser/stop-cloud-browser-session")
    assert stop_call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer frontend-id-token",
        "X-Narada-User-ID": "user-123",
        "X-Narada-Env": "dev",
    }


@pytest.mark.asyncio
async def test_open_and_initialize_cloud_browser_window_raises_when_version_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "packages": {"narada-pyodide": {"min_required_version": "999.0.0"}}
            }
        )
    )
    narada_pkg, client_module, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    monkeypatch.setattr(client_module, "__version__", "unknown")

    with pytest.raises(InvalidVersion) as exc_info:
        async with narada_pkg.Narada(api_key="test-api-key"):
            pass

    assert "Invalid version: 'unknown'" in str(exc_info.value)
    assert pyfetch.await_count == 1


@pytest.mark.asyncio
async def test_cloud_browser_window_close_stops_cloud_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(return_value=_FakeResponse(json_data={"success": True}))
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    await window.close()

    call = pyfetch.await_args
    assert call is not None
    assert call.args[0].endswith("/cloud-browser/stop-cloud-browser-session")
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["headers"] == {
        "x-api-key": "test-api-key",
        "Content-Type": "application/json",
    }
    assert json.loads(call.kwargs["body"]) == {"session_id": "session-123"}


@pytest.mark.asyncio
async def test_cloud_browser_window_dispatch_request_omits_parent_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    window_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.dispatch_request(prompt="hello from cloud browser")

    assert response["status"] == "success"
    post_call = pyfetch.await_args_list[0]
    assert post_call.args[0].endswith("/remote-dispatch")
    assert post_call.kwargs["method"] == "POST"
    payload = json.loads(post_call.kwargs["body"])
    assert payload["browserWindowId"] == "browser-window-123"
    assert payload["cloudBrowserSessionId"] == "session-123"
    assert payload["prompt"] == "/Operator hello from cloud browser"
    assert "parentRunIds" not in payload


@pytest.mark.asyncio
async def test_cloud_browser_window_dispatch_request_waits_through_active_input_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-123"}),
            _FakeResponse(
                json_data={
                    "status": "input-required",
                    "completedAt": None,
                    "response": None,
                    "activeInputRequest": {
                        "inputId": "input-123",
                        "action": {
                            "name": "prompt_for_user_input",
                            "step_id": "step-123",
                            "variables": [
                                {
                                    "name": "email",
                                    "type": "string",
                                    "required": True,
                                }
                            ],
                        },
                    },
                }
            ),
            _FakeResponse(
                json_data={
                    "status": "input-required",
                    "completedAt": None,
                    "response": None,
                    "activeInputRequest": {
                        "inputId": "input-123",
                        "action": {
                            "name": "prompt_for_user_input",
                            "step_id": "step-123",
                            "variables": [
                                {
                                    "name": "email",
                                    "type": "string",
                                    "required": True,
                                }
                            ],
                        },
                    },
                }
            ),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    sleep = AsyncMock()
    on_input_required = AsyncMock()
    monkeypatch.setattr(window_module.asyncio, "sleep", sleep)

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.dispatch_request(
        prompt="hello from cloud browser",
        on_input_required=on_input_required,
    )

    assert response["status"] == "success"
    assert pyfetch.await_count == 4
    assert sleep.await_count == 2
    on_input_required.assert_awaited_once()
    active_input_request = on_input_required.await_args.args[0]
    assert active_input_request.input_id == "input-123"
    assert active_input_request.action.name == "prompt_for_user_input"
    first_poll_call = pyfetch.await_args_list[1]
    second_poll_call = pyfetch.await_args_list[3]
    assert first_poll_call.args[0].endswith("/remote-dispatch/responses/req-123")
    assert second_poll_call.args[0].endswith("/remote-dispatch/responses/req-123")


@pytest.mark.asyncio
async def test_cloud_browser_window_dispatch_request_keeps_parent_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "child-request-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    window_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])
    monkeypatch.setattr(
        builtins, "_narada_request_id", "parent-request-123", raising=False
    )

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.dispatch_request(prompt="hello from cloud browser")

    assert response["status"] == "success"
    post_call = pyfetch.await_args_list[0]
    payload = json.loads(post_call.kwargs["body"])
    assert payload["parentRequestId"] == "parent-request-123"
    assert "parentRunIds" not in payload


@pytest.mark.asyncio
async def test_window_agent_keeps_parent_request_id_from_injected_builtins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "child-request-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "response": {
                        "text": "done",
                        "output": {"type": "text", "content": "done"},
                    },
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "usage": {"actions": 0, "credits": 0},
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    window_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])
    monkeypatch.setattr(
        builtins, "_narada_request_id", "parent-request-123", raising=False
    )

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.agent(prompt="run gui child", agent="/$USER/gui-child")

    assert response.status == "success"
    post_call = pyfetch.await_args_list[0]
    payload = json.loads(post_call.kwargs["body"])
    assert payload["parentRequestId"] == "parent-request-123"


@pytest.mark.asyncio
async def test_window_agent_exposes_workflow_trace_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_trace = {"step_type": "workflow", "children": []}
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "child-request-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "response": {
                        "text": "done",
                        "output": {"type": "text", "content": "done"},
                        "workflowTrace": workflow_trace,
                    },
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "usage": {"actions": 0, "credits": 0},
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.agent(prompt="return a trace")

    assert response.workflow_trace == workflow_trace
    assert response.model_dump(by_alias=True)["workflowTrace"] == workflow_trace
    sub_workflow_events = [
        json.loads(event)
        for event in emitted_events
        if json.loads(event)["kind"] == "subWorkflow"
    ]
    assert sub_workflow_events == [
        {"kind": "subWorkflow", "workflowTrace": workflow_trace}
    ]


@pytest.mark.asyncio
async def test_cloud_browser_window_dispatch_request_retries_poll_fetch_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-123"}),
            RuntimeError("temporary fetch failure"),
            _FakeResponse(ok=False, status=502, text_data="bad gateway"),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    sleep_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    retry_module = sys.modules["narada.retry"]
    monkeypatch.setattr(retry_module.asyncio, "sleep", fake_sleep)

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.dispatch_request(prompt="hello from cloud browser")

    assert response["status"] == "success"
    assert pyfetch.await_count == 4
    assert sleep_delays == [0.5, 1.0]


@pytest.mark.asyncio
async def test_pyfetch_with_retries_does_not_start_retry_at_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(ok=False, status=502, text_data="bad gateway")
    )
    _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    retry_module = sys.modules["narada.retry"]
    sleep = AsyncMock()

    monkeypatch.setattr(retry_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(retry_module.time, "monotonic", lambda: 10.0)

    response = await retry_module.pyfetch_with_retries(
        "https://example.test/retry",
        retry_deadline=10.5,
    )

    assert response.status == 502
    assert pyfetch.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_request_emits_string_trace_agent_type_for_sdk_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    narada_pkg, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.dispatch_request(
        prompt="hello from cloud browser",
        agent=narada_pkg.Agent.OPERATOR,
    )

    assert response["status"] == "success"
    assert json.loads(pyfetch.await_args_list[0].kwargs["body"])["prompt"] == (
        "/Operator hello from cloud browser"
    )
    assert len(emitted_events) == 1
    assert json.loads(emitted_events[0])["agent_type"] == "operator"


@pytest.mark.asyncio
async def test_dispatch_request_emits_success_text_in_sub_agent_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": {
                        "text": "TRACE_CORE_AGENT_DONE",
                        "actionTrace": [],
                    },
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    narada_pkg, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.dispatch_request(
        prompt="reply with marker",
        agent=narada_pkg.Agent.CORE_AGENT,
    )

    from narada_core.tracing.model import PythonSubAgentCallEvent

    assert response["status"] == "success"
    assert len(emitted_events) == 1
    event = json.loads(emitted_events[0])
    parsed_event = PythonSubAgentCallEvent.model_validate(event)
    assert parsed_event.agent_type == "coreAgent"
    assert parsed_event.text == "TRACE_CORE_AGENT_DONE"
    assert parsed_event.action_trace == []


@pytest.mark.asyncio
async def test_dispatch_request_emits_input_required_sub_agent_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-123"}),
            _FakeResponse(
                json_data={
                    "status": "input-required",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": {
                        "text": "TRACE_INPUT_REQUIRED",
                        "output": {"type": "text", "content": "TRACE_INPUT_REQUIRED"},
                    },
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.dispatch_request(prompt="needs input")

    from narada_core.tracing.model import PythonSubAgentCallEvent

    assert response["status"] == "input-required"
    assert len(emitted_events) == 1
    parsed_event = PythonSubAgentCallEvent.model_validate(json.loads(emitted_events[0]))
    assert parsed_event.status == "input-required"
    assert parsed_event.text == "TRACE_INPUT_REQUIRED"


def test_parse_action_trace_preserves_run_custom_agent_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(CORE_SRC))

    from narada_core.tracing.model import parse_action_trace

    parsed_trace = parse_action_trace(
        [
            {
                "step_type": "runCustomAgent",
                "url": "https://example.com",
                "workflow_id": "workflow-parent",
                "workflow_name": "Parent workflow",
                "status": "success",
                "children": [
                    {
                        "step_type": "print",
                        "url": "https://example.com",
                        "message": "TRACE_GUI_CHILD_DONE",
                    }
                ],
            }
        ]
    )

    assert parsed_trace[0].step_type == "runCustomAgent"
    assert parsed_trace[0].children is not None
    assert parsed_trace[0].children[0].step_type == "print"
    assert parsed_trace[0].children[0].message == "TRACE_GUI_CHILD_DONE"


@pytest.mark.asyncio
async def test_cloud_browser_window_dispatch_request_preserves_current_file_variable_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    file_variable = {
        "source": "agentStudioAttachment",
        "id": "file-123",
        "filename": "report.pdf",
        "mimeType": "application/pdf",
        "itemId": "workflow-123",
    }

    response = await window.dispatch_request(
        prompt="summarize {{ $doc }}",
        input_variables={"doc": file_variable},
    )

    assert response["status"] == "success"
    payload = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    assert payload["inputVariables"] == {"doc": file_variable}


@pytest.mark.asyncio
async def test_cloud_browser_window_get_downloaded_files_returns_presigned_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(
                json_data={
                    "downloaded_files": [
                        {
                            "file_name": "report.pdf",
                            "key": "downloads/session-123/report.pdf",
                            "size": 42,
                        }
                    ]
                }
            ),
            _FakeResponse(
                json_data={"presigned_url": "https://example.com/report.pdf"}
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    files = await window.get_downloaded_files()

    assert files == [
        window_module.SessionDownloadItem(
            file_name="report.pdf",
            size=42,
            download_url="https://example.com/report.pdf",
        )
    ]
    assert pyfetch.await_count == 2
    first_call, second_call = pyfetch.await_args_list
    assert "session_id=session-123" in first_call.args[0]
    assert first_call.args[0].endswith(
        "/cloud-browser/replay/downloads?session_id=session-123"
    )
    assert "session_id=session-123" in second_call.args[0]
    assert "key=downloads%2Fsession-123%2Freport.pdf" in second_call.args[0]


@pytest.mark.asyncio
async def test_remote_browser_window_prompt_for_user_input_uses_hitl_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "status": "success",
                "data": '{"values_by_name":{"name":"Narada"}}',
            }
        )
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.RemoteBrowserWindow(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    values = await window.prompt_for_user_input(
        step_id="input-step",
        variables=[
            window_module.PromptForUserInputVariable(
                name="name", type="string", required=True
            ),
        ],
    )

    assert values == {"name": "Narada"}
    call = pyfetch.await_args
    assert call is not None
    payload = json.loads(call.kwargs["body"])
    assert payload["timeout"] == window_module.DEFAULT_HITL_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_remote_browser_window_user_approval_respects_explicit_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={"status": "success", "data": '{"approved":true}'}
        )
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.RemoteBrowserWindow(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    approved = await window.user_approval(
        step_id="approval-step",
        prompt_message="Proceed?",
        approve_label="Approve",
        reject_label="Reject",
        timeout=600,
    )

    assert approved is True
    call = pyfetch.await_args
    assert call is not None
    payload = json.loads(call.kwargs["body"])
    assert payload["timeout"] == 600


@pytest.mark.asyncio
async def test_remote_browser_window_without_cloud_session_keeps_extension_action_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    window_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])

    window = window_module.RemoteBrowserWindow(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    await window.close()

    call = pyfetch.await_args
    assert call is not None
    assert call.args[0].endswith("/extension-actions")
    assert call.kwargs["method"] == "POST"
    payload = json.loads(call.kwargs["body"])
    assert payload["browserWindowId"] == "browser-window-123"
    assert payload["action"]["name"] == "close_window"
    assert "parentRunIds" not in payload


@pytest.mark.asyncio
async def test_extension_action_includes_remote_dispatch_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_REMOTE_DISPATCH_REQUEST_ID", "request-123")
    monkeypatch.setenv("NARADA_REMOTE_DISPATCH_API_KEY_ID", "api-key-123")
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.RemoteBrowserWindow(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    await window.close()

    call = pyfetch.await_args
    assert call is not None
    payload = json.loads(call.kwargs["body"])
    assert payload["requestId"] == "request-123"
    assert payload["apiKeyId"] == "api-key-123"


@pytest.mark.asyncio
async def test_extension_action_prefers_remote_dispatch_request_id_over_parent_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # In a nested remote-dispatch run, the env-injected request id (the request the
    # external caller polls and the frontend status reporter targets) differs from the
    # builtins parent request id (a separate observability dispatch id). The env value
    # must win so input-required status is reported to the request the caller is polling.
    monkeypatch.setenv(
        "NARADA_REMOTE_DISPATCH_REQUEST_ID", "remote-dispatch-request-123"
    )
    monkeypatch.setenv("NARADA_REMOTE_DISPATCH_API_KEY_ID", "api-key-123")
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    monkeypatch.setattr(
        builtins, "_narada_request_id", "observability-dispatch-456", raising=False
    )

    window = window_module.RemoteBrowserWindow(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    await window.close()

    call = pyfetch.await_args
    assert call is not None
    payload = json.loads(call.kwargs["body"])
    assert payload["requestId"] == "remote-dispatch-request-123"
    assert payload["apiKeyId"] == "api-key-123"


@pytest.mark.asyncio
async def test_remote_browser_window_extension_action_keeps_parent_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    window_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])
    monkeypatch.setattr(
        builtins, "_narada_request_id", "parent-request-123", raising=False
    )

    window = window_module.RemoteBrowserWindow(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    await window.close()

    call = pyfetch.await_args
    assert call is not None
    payload = json.loads(call.kwargs["body"])
    assert payload["requestId"] == "parent-request-123"
    assert "parentRunIds" not in payload


@pytest.mark.asyncio
async def test_local_browser_window_dispatch_request_uses_latest_parent_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_API_KEY", "test-api-key")
    monkeypatch.setenv("NARADA_BROWSER_WINDOW_ID", "browser-window-123")
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-1"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
            _FakeResponse(json_data={"requestId": "req-2"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.LocalBrowserWindow()

    window_module._narada_parent_run_ids = _FakeJsProxy(["run-a"])
    first_response = await window.dispatch_request(prompt="first prompt")

    window_module._narada_parent_run_ids = _FakeJsProxy(["run-b", "run-c"])
    second_response = await window.dispatch_request(prompt="second prompt")

    assert first_response["status"] == "success"
    assert second_response["status"] == "success"

    first_post = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    second_post = json.loads(pyfetch.await_args_list[2].kwargs["body"])
    assert first_post["parentRunIds"] == ["run-a"]
    assert second_post["parentRunIds"] == ["run-b", "run-c"]


@pytest.mark.asyncio
async def test_local_browser_window_dispatch_request_includes_parent_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_API_KEY", "test-api-key")
    monkeypatch.setenv("NARADA_BROWSER_WINDOW_ID", "browser-window-123")
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "child-request-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "activeInputRequest": None,
                }
            ),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    window_module._narada_parent_run_ids = _FakeJsProxy(["run-a"])
    monkeypatch.setattr(
        builtins, "_narada_request_id", "parent-request-123", raising=False
    )

    window = window_module.LocalBrowserWindow()
    response = await window.dispatch_request(prompt="child prompt")

    assert response["status"] == "success"
    post_payload = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    assert post_payload["parentRequestId"] == "parent-request-123"
    assert post_payload["parentRunIds"] == ["run-a"]


@pytest.mark.asyncio
async def test_local_browser_window_extension_action_includes_parent_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_API_KEY", "test-api-key")
    monkeypatch.setenv("NARADA_BROWSER_WINDOW_ID", "browser-window-123")
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    window_module._narada_parent_run_ids = _FakeJsProxy(["run-a"])
    monkeypatch.setattr(
        builtins, "_narada_request_id", "parent-request-123", raising=False
    )

    window = window_module.LocalBrowserWindow()
    await window.close()

    post_payload = json.loads(pyfetch.await_args.kwargs["body"])
    assert post_payload["requestId"] == "parent-request-123"
    assert post_payload["parentRunIds"] == ["run-a"]

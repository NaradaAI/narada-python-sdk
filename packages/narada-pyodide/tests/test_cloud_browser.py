from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from narada_core.actions.models import (
    DEFAULT_HITL_TIMEOUT_SECONDS,
    PromptForUserInputVariable,
)
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


def _sdk_config_response() -> _FakeResponse:
    return _FakeResponse(
        json_data={"packages": {"narada-pyodide": {"min_required_version": "0.0.1"}}}
    )


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
    env_module = importlib.import_module("narada.environment")
    env_module._narada_parent_run_ids = _FakeJsProxy([])
    env_module._narada_request_id = None
    monkeypatch.setattr(builtins, "_narada_request_id", None, raising=False)
    env_module._narada_get_id_token = AsyncMock(return_value="frontend-id-token")
    return narada_pkg, env_module


@pytest.mark.asyncio
async def test_cloud_browser_environment_maps_backend_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", "request-maps-123"
    )
    pyfetch = AsyncMock(
        side_effect=[
            _sdk_config_response(),
            _FakeResponse(
                json_data={
                    "session_id": "session-123",
                    "session_name": "demo",
                    "browser_window_id": "browser-window-123",
                }
            ),
        ]
    )
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.CloudBrowserEnvironment(
        api_key="test-api-key",
        session_name="demo",
        session_timeout=321,
    )
    await env.start()

    assert env.browser_window_id == "browser-window-123"
    assert env.cloud_browser_session_id == "session-123"

    create_call = pyfetch.await_args_list[1]
    assert create_call.args[0].endswith(
        "/cloud-browser/create-and-initialize-cloud-browser-session"
    )
    assert create_call.kwargs["method"] == "POST"
    assert create_call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "x-api-key": "test-api-key",
    }
    assert json.loads(create_call.kwargs["body"]) == {
        "session_name": "demo",
        "session_timeout": 321,
        "require_extension": True,
        "initiator_remote_dispatch_request_id": "request-maps-123",
    }


@pytest.mark.asyncio
async def test_lambda_environment_uses_extensionless_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", "request-lambda-123"
    )
    pyfetch = AsyncMock(
        side_effect=[
            _sdk_config_response(),
            _FakeResponse(
                json_data={
                    "session_id": "session-123",
                    "browser_window_id": "browser-window-123",
                }
            ),
        ]
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.LambdaEnvironment(
        api_key="test-api-key",
        session_name="lambda-session",
        session_timeout=300,
    )
    await env.start()

    assert env.session_id == "session-123"
    create_call = pyfetch.await_args_list[1]
    assert json.loads(create_call.kwargs["body"]) == {
        "session_name": "lambda-session",
        "session_timeout": 300,
        "require_extension": False,
        "initiator_remote_dispatch_request_id": "request-lambda-123",
    }


@pytest.mark.asyncio
async def test_cloud_browser_environment_requires_initiator_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", raising=False)
    pyfetch = AsyncMock(side_effect=[_sdk_config_response()])
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.CloudBrowserEnvironment(api_key="test-api-key")
    with pytest.raises(ValueError, match="NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID"):
        await env.start()

    assert pyfetch.await_count == 1


@pytest.mark.asyncio
async def test_cloud_browser_environment_supports_frontend_bearer_auth(
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
            _sdk_config_response(),
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
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.CloudBrowserEnvironment(session_name="demo", session_timeout=321)
    await env.start()
    await env.close()

    for call in pyfetch.await_args_list:
        assert call.kwargs["headers"] == {
            "Content-Type": "application/json",
            "Authorization": "Bearer frontend-id-token",
            "X-Narada-User-ID": "user-123",
            "X-Narada-Env": "dev",
        }


@pytest.mark.asyncio
async def test_cloud_browser_environment_raises_when_version_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "packages": {"narada-pyodide": {"min_required_version": "999.0.0"}}
            }
        )
    )
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    monkeypatch.setattr(env_module, "__version__", "unknown")

    env = narada_pkg.CloudBrowserEnvironment(api_key="test-api-key")
    with pytest.raises(InvalidVersion) as exc_info:
        await env.start()

    assert "Invalid version: 'unknown'" in str(exc_info.value)
    assert pyfetch.await_count == 1


@pytest.mark.asyncio
async def test_remote_browser_environment_close_stops_cloud_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(return_value=_FakeResponse(json_data={"success": True}))
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    await env.close()

    call = pyfetch.await_args
    assert call is not None
    assert call.args[0].endswith("/cloud-browser/stop-cloud-browser-session")
    assert call.kwargs["method"] == "POST"
    assert json.loads(call.kwargs["body"]) == {"session_id": "session-123"}


@pytest.mark.asyncio
async def test_remote_browser_environment_dispatch_omits_parent_run_ids(
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
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    env_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    response = await env._dispatch_request(prompt="hello from cloud browser")

    assert response["status"] == "success"
    payload = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    assert payload["browserWindowId"] == "browser-window-123"
    assert payload["cloudBrowserSessionId"] == "session-123"
    assert payload["prompt"] == "/Operator hello from cloud browser"
    assert "parentRunIds" not in payload


@pytest.mark.asyncio
async def test_dispatch_request_waits_through_hitl_input_required(
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
                    "hitlInputMetadata": {
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
                    "hitlInputMetadata": {
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
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    sleep = AsyncMock()
    on_input_required = AsyncMock()
    monkeypatch.setattr(env_module.asyncio, "sleep", sleep)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    response = await env._dispatch_request(
        prompt="hello from cloud browser",
        on_input_required=on_input_required,
    )

    assert response["status"] == "success"
    assert pyfetch.await_count == 4
    assert sleep.await_count == 2
    on_input_required.assert_awaited_once()
    hitl_input_metadata = on_input_required.await_args.args[0]
    assert hitl_input_metadata.input_id == "input-123"
    assert hitl_input_metadata.action.name == "prompt_for_user_input"


@pytest.mark.asyncio
async def test_agent_run_keeps_parent_request_id_from_injected_builtins(
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
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    env_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])
    monkeypatch.setattr(
        builtins, "_narada_request_id", "parent-request-123", raising=False
    )

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    response = await narada_pkg.Agent(environment=env, kind="/$USER/gui-child").run(
        "run gui child"
    )

    assert response.status == "success"
    payload = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    assert payload["parentRequestId"] == "parent-request-123"


@pytest.mark.asyncio
async def test_agent_run_forwards_clear_chat(
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
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    await narada_pkg.Agent(environment=env).run("fresh task", clear_chat=True)

    payload = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    assert payload["clearChat"] is True


@pytest.mark.asyncio
async def test_agent_run_forwards_test_mode(
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
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    await narada_pkg.Agent(environment=env).run(
        "/agentMaker repair workflow", test=True
    )

    payload = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    assert payload["prompt"] == "/agentMaker repair workflow"
    assert payload["test"] is True


@pytest.mark.asyncio
async def test_agent_run_exposes_workflow_trace_alias(
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
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    response = await narada_pkg.Agent(environment=env).run("return a trace")

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
async def test_agent_run_emits_combined_critic_workflow_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_trace = {
        "workflowId": "main-workflow",
        "workflowName": "Main Workflow",
        "runtime": "gui",
        "status": "success",
        "startTs": 100,
        "children": [],
    }
    critic_workflow_trace = {
        "workflowId": "critic-workflow",
        "workflowName": "Critic Workflow",
        "runtime": "gui",
        "status": "success",
        "startTs": 200,
        "children": [],
    }
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "main-request-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": {
                        "text": "done",
                        "output": {"type": "text", "content": "done"},
                        "workflowTrace": workflow_trace,
                    },
                    "usage": {"actions": 0, "credits": 0},
                    "hitlInputMetadata": None,
                }
            ),
            _FakeResponse(json_data={"requestId": "critic-request-123"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": {
                        "text": '{"narada_validation_passed":true}',
                        "output": {
                            "type": "structured",
                            "content": {"narada_validation_passed": True},
                        },
                        "workflowTrace": critic_workflow_trace,
                    },
                    "usage": {"actions": 0, "credits": 0},
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    response = await narada_pkg.Agent(environment=env).run("return a trace", critic={})

    combined_workflow_trace = {
        **workflow_trace,
        "children": [{"kind": "sub_workflow", "trace": critic_workflow_trace}],
    }
    assert response.critic_result is not None
    assert response.critic_result.workflow_trace == critic_workflow_trace
    assert response.workflow_trace == combined_workflow_trace
    sub_workflow_events = [
        json.loads(event)
        for event in emitted_events
        if json.loads(event)["kind"] == "subWorkflow"
    ]
    assert sub_workflow_events == [
        {"kind": "subWorkflow", "workflowTrace": combined_workflow_trace}
    ]


@pytest.mark.asyncio
async def test_dispatch_request_retries_poll_fetch_failures(
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
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    sleep_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    retry_module = sys.modules["narada.retry"]
    monkeypatch.setattr(retry_module.asyncio, "sleep", fake_sleep)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    response = await env._dispatch_request(prompt="hello from cloud browser")

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
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    response = await env._dispatch_request(
        prompt="hello from cloud browser",
        agent=narada_pkg.AgentKind.OPERATOR,
    )

    assert response["status"] == "success"
    assert json.loads(pyfetch.await_args_list[0].kwargs["body"])["prompt"] == (
        "/Operator hello from cloud browser"
    )
    assert len(emitted_events) == 1
    assert json.loads(emitted_events[0])["agent_type"] == "operator"


@pytest.mark.asyncio
async def test_dispatch_request_emits_success_text_and_execution_trace_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_trace_context = {
        "type": "executionTraceContext",
        "schemaVersion": 1,
        "label": "cloud child",
        "traceId": "trace-parent",
        "segmentId": "segment-cloud",
        "executionTraceS3Key": "s3://trace/segment-cloud/index.json",
        "executionTraceSegmentS3Key": "s3://trace/segment-cloud/index.json",
        "status": "completed",
    }
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
                        "executionTraceContext": execution_trace_context,
                    },
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    response = await env._dispatch_request(
        prompt="reply with marker",
        agent=narada_pkg.AgentKind.CORE_AGENT,
    )

    from narada_core.tracing.model import PythonSubAgentCallEvent

    assert response["status"] == "success"
    assert len(emitted_events) == 1
    parsed_event = PythonSubAgentCallEvent.model_validate(json.loads(emitted_events[0]))
    assert parsed_event.agent_type == "coreAgent"
    assert parsed_event.text == "TRACE_CORE_AGENT_DONE"
    assert parsed_event.execution_trace_context == execution_trace_context


@pytest.mark.asyncio
async def test_dispatch_request_preserves_current_file_variable_shape(
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
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    file_variable = {
        "source": "agentStudioAttachment",
        "id": "file-123",
        "filename": "report.pdf",
        "mimeType": "application/pdf",
        "itemId": "workflow-123",
    }

    response = await env._dispatch_request(
        prompt="summarize {{ $doc }}",
        input_variables={"doc": file_variable},
    )

    assert response["status"] == "success"
    payload = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    assert payload["inputVariables"] == {"doc": file_variable}


@pytest.mark.asyncio
async def test_dispatch_request_rejects_file_uploads_in_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import BytesIO

    pyfetch = AsyncMock()
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )

    # Reading file contents from disk is not possible in the browser, so passing a file-like
    # object (rather than an already-uploaded reference) must fail fast instead of attempting
    # an upload over the network.
    file_obj = BytesIO(b"hello")
    file_obj.name = "report.txt"

    with pytest.raises(
        NotImplementedError, match="not supported in the browser environment"
    ):
        await env._dispatch_request(
            prompt="summarize {{ $doc }}",
            input_variables={"doc": file_obj},
        )

    pyfetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_browser_downloads_return_presigned_urls(
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
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        api_key="test-api-key",
    )
    files = await env.get_downloaded_files()

    assert files == [
        env_module.SessionDownloadItem(
            file_name="report.pdf",
            size=42,
            download_url="https://example.com/report.pdf",
        )
    ]
    first_call, second_call = pyfetch.await_args_list
    assert first_call.args[0].endswith(
        "/cloud-browser/replay/downloads?session_id=session-123"
    )
    assert "key=downloads%2Fsession-123%2Freport.pdf" in second_call.args[0]


@pytest.mark.asyncio
async def test_lambda_environment_downloads_return_presigned_urls(
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
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.LambdaEnvironment(api_key="test-api-key")
    env._session_id = "session-123"
    files = await env.get_downloaded_files()

    assert files == [
        env_module.SessionDownloadItem(
            file_name="report.pdf",
            size=42,
            download_url="https://example.com/report.pdf",
        )
    ]
    first_call, second_call = pyfetch.await_args_list
    assert first_call.args[0].endswith(
        "/cloud-browser/replay/downloads?session_id=session-123"
    )
    assert "key=downloads%2Fsession-123%2Freport.pdf" in second_call.args[0]


@pytest.mark.asyncio
async def test_agent_prompt_for_user_input_uses_hitl_default_timeout(
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
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    agent = narada_pkg.Agent(environment=env)
    values = await agent.prompt_for_user_input(
        step_id="input-step",
        variables=[
            PromptForUserInputVariable(name="name", type="string", required=True),
        ],
    )

    assert values == {"name": "Narada"}
    payload = json.loads(pyfetch.await_args.kwargs["body"])
    assert payload["timeout"] == DEFAULT_HITL_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_agentic_mouse_action_preserves_resize_window_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    await narada_pkg.Agent(environment=env).agentic_mouse_action(
        action={"type": "click"},
        recorded_click={"x": 500, "y": 300, "viewport": {"width": 1280, "height": 720}},
        fallback_operator_query="click the target",
        resize_window=False,
    )

    payload = json.loads(pyfetch.await_args.kwargs["body"])
    assert payload["action"]["resize_window"] is False


@pytest.mark.asyncio
async def test_agentic_mouse_action_returns_verification_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={"status": "success", "data": '{"verified":true}'}
        )
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    verified = await narada_pkg.Agent(environment=env).agentic_mouse_action(
        action={"type": "click"},
        recorded_click={"x": 500, "y": 300, "viewport": {"width": 1280, "height": 720}},
        fallback_operator_query="click the target",
        verification_description="The target was clicked.",
        verification_delay_ms=750,
    )

    assert verified is True
    payload = json.loads(pyfetch.await_args.kwargs["body"])
    assert payload["action"] == {
        "name": "agentic_mouse_action",
        "action": {"type": "click"},
        "recorded_click": {
            "x": 500,
            "y": 300,
            "viewport": {"width": 1280, "height": 720},
        },
        "resize_window": True,
        "fallback_operator_query": "click the target",
        "verification_description": "The target was clicked.",
        "verification_delay_ms": 750,
    }


@pytest.mark.asyncio
async def test_agent_user_approval_respects_explicit_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={"status": "success", "data": '{"approved":true}'}
        )
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    approved = await narada_pkg.Agent(environment=env).user_approval(
        step_id="approval-step",
        prompt_message="Proceed?",
        approve_label="Approve",
        reject_label="Reject",
        timeout=600,
    )

    assert approved is True
    payload = json.loads(pyfetch.await_args.kwargs["body"])
    assert payload["timeout"] == 600


@pytest.mark.asyncio
async def test_remote_browser_environment_without_cloud_session_uses_extension_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    env_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    await env.close()

    payload = json.loads(pyfetch.await_args.kwargs["body"])
    assert payload["browserWindowId"] == "browser-window-123"
    assert payload["action"]["name"] == "close_window"
    assert "parentRunIds" not in payload


@pytest.mark.asyncio
async def test_agent_execute_javascript_on_page_dispatches_extension_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "status": "success",
                "data": '{"result":{"title":"Example Domain","count":3}}',
            }
        )
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    result = await narada_pkg.Agent(environment=env).execute_javascript_on_page(
        code="(() => ({ title: document.title, count: 3 }))()",
    )

    assert result == {"title": "Example Domain", "count": 3}
    call = pyfetch.await_args
    assert call is not None
    payload = json.loads(call.kwargs["body"])
    assert payload["action"] == {
        "name": "execute_javascript_on_page",
        "code": "(() => ({ title: document.title, count: 3 }))()",
    }


@pytest.mark.asyncio
async def test_extension_action_includes_remote_dispatch_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_REMOTE_DISPATCH_REQUEST_ID", "request-123")
    monkeypatch.setenv("NARADA_REMOTE_DISPATCH_API_KEY_ID", "api-key-123")
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    await env.close()

    payload = json.loads(pyfetch.await_args.kwargs["body"])
    assert payload["requestId"] == "request-123"
    assert payload["apiKeyId"] == "api-key-123"
    assert payload["actionExecutionId"].startswith("action_")


@pytest.mark.asyncio
async def test_extension_action_request_and_trace_share_action_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "status": "success",
                "data": json.dumps({"url": "https://example.com"}),
            }
        )
    )
    narada_pkg, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sys.modules["narada._trace"],
        "_narada_emit_trace_event",
        emitted_events.append,
        raising=False,
    )

    env = narada_pkg.RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    assert (
        await narada_pkg.Agent(environment=env).get_url()
    ).url == "https://example.com"

    request_body = json.loads(pyfetch.await_args.kwargs["body"])
    assert request_body["actionExecutionId"].startswith("action_")
    assert len(emitted_events) == 1
    trace_event = json.loads(emitted_events[0])
    assert trace_event["kind"] == "extensionAction"
    assert trace_event["action_name"] == "get_url"
    assert trace_event["action_execution_id"] == request_body["actionExecutionId"]


@pytest.mark.asyncio
async def test_local_browser_environment_dispatch_uses_latest_parent_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_API_KEY", "test-api-key")
    monkeypatch.setenv("NARADA_BROWSER_WINDOW_ID", "browser-window-123")
    monkeypatch.setenv(
        "NARADA_EXECUTION_TRACE_CONTEXT",
        json.dumps(
            {
                "type": "executionTraceInheritanceContext",
                "schemaVersion": 1,
                "traceId": "trace-parent",
                "parentSegmentId": "segment-local",
            }
        ),
    )
    pyfetch = AsyncMock(
        side_effect=[
            _sdk_config_response(),
            _FakeResponse(json_data={"requestId": "req-1"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "hitlInputMetadata": None,
                }
            ),
            _FakeResponse(json_data={"requestId": "req-2"}),
            _FakeResponse(
                json_data={
                    "status": "success",
                    "completedAt": "2026-05-08T00:00:00+00:00",
                    "response": None,
                    "hitlInputMetadata": None,
                }
            ),
        ]
    )
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    env = narada_pkg.BrowserEnvironment()

    env_module._narada_parent_run_ids = _FakeJsProxy(["run-a"])
    first_response = await env._dispatch_request(prompt="first prompt")

    env_module._narada_parent_run_ids = _FakeJsProxy(["run-b", "run-c"])
    second_response = await env._dispatch_request(prompt="second prompt")

    assert first_response["status"] == "success"
    assert second_response["status"] == "success"

    first_post = json.loads(pyfetch.await_args_list[1].kwargs["body"])
    second_post = json.loads(pyfetch.await_args_list[3].kwargs["body"])
    assert first_post["parentRunIds"] == ["run-a"]
    assert second_post["parentRunIds"] == ["run-b", "run-c"]
    assert first_post["executionTraceContext"] == {
        "type": "executionTraceInheritanceContext",
        "schemaVersion": 1,
        "traceId": "trace-parent",
        "parentSegmentId": "segment-local",
    }
    assert second_post["executionTraceContext"] == first_post["executionTraceContext"]


@pytest.mark.asyncio
async def test_local_browser_environment_extension_action_includes_parent_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_API_KEY", "test-api-key")
    monkeypatch.setenv("NARADA_BROWSER_WINDOW_ID", "browser-window-123")
    pyfetch = AsyncMock(
        side_effect=[
            _sdk_config_response(),
            _FakeResponse(json_data={"status": "success", "data": None}),
        ]
    )
    narada_pkg, env_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    env_module._narada_parent_run_ids = _FakeJsProxy(["run-a"])
    monkeypatch.setattr(
        builtins, "_narada_request_id", "parent-request-123", raising=False
    )

    env = narada_pkg.BrowserEnvironment()
    await env.close()

    post_payload = json.loads(pyfetch.await_args_list[1].kwargs["body"])
    assert post_payload["requestId"] == "parent-request-123"
    assert post_payload["parentRunIds"] == ["run-a"]

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from narada import Agent, Environment, trace


class _FakeResponse:
    ok = True
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self._payload


class _RemoteDispatchFakeClientSession:
    def __init__(self) -> None:
        self.dispatched_bodies: list[dict[str, Any]] = []
        self._poll_count = 0

    async def __aenter__(self) -> "_RemoteDispatchFakeClientSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        if url.endswith("/remote-dispatch"):
            self.dispatched_bodies.append(kwargs["json"])
            return _FakeResponse({"requestId": f"req-{len(self.dispatched_bodies)}"})
        raise AssertionError(f"Unexpected POST URL: {url}")

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        if "/remote-dispatch/responses/" not in url:
            raise AssertionError(f"Unexpected GET URL: {url}")

        self._poll_count += 1
        return _FakeResponse(
            {
                "status": "success",
                "response": {
                    "text": f"ok-{self._poll_count}",
                    "output": {"type": "text", "content": f"ok-{self._poll_count}"},
                },
                "usage": {"actions": 1, "credits": 1},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "activeInputRequest": None,
            }
        )


class _CountingEnvironment(Environment):
    def __init__(self) -> None:
        super().__init__(auth_headers={})
        self.initialize_count = 0

    @property
    def _validates_sdk_config(self) -> bool:
        return False

    async def _initialize(self) -> None:
        self.initialize_count += 1


@pytest.mark.asyncio
async def test_agent_run_reruns_but_environment_initialization_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_session = _RemoteDispatchFakeClientSession()
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    env = _CountingEnvironment()
    agent = Agent(environment=env)

    first = await agent.run("first")
    second = await agent.run("second")

    assert env.initialize_count == 1
    assert first.request_id == "req-1"
    assert second.request_id == "req-2"
    assert [body["prompt"] for body in fake_session.dispatched_bodies] == [
        "/Operator first",
        "/Operator second",
    ]
    assert all(
        "captureExecutionTrace" not in body for body in fake_session.dispatched_bodies
    )


@pytest.mark.asyncio
async def test_agent_run_forwards_clear_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_session = _RemoteDispatchFakeClientSession()
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    env = _CountingEnvironment()
    agent = Agent(environment=env)

    await agent.run("fresh task", clear_chat=True)

    assert fake_session.dispatched_bodies[0]["clearChat"] is True


@pytest.mark.asyncio
async def test_agent_run_exposes_execution_trace_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    execution_trace_context = {
        "type": "executionTraceContext",
        "label": "Trace",
        "traceId": "trace-1",
        "executionTraceS3Key": "user-test/recording-trace-1/execution-trace/index.json",
    }
    fake_session = _RemoteDispatchFakeClientSession()

    def get_with_trace(url: str, **kwargs: Any) -> _FakeResponse:
        del kwargs
        if "/remote-dispatch/responses/" not in url:
            raise AssertionError(f"Unexpected GET URL: {url}")
        return _FakeResponse(
            {
                "status": "success",
                "response": {
                    "text": "ok",
                    "output": {"type": "text", "content": "ok"},
                    "executionTraceContext": execution_trace_context,
                },
                "usage": {"actions": 1, "credits": 1},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "activeInputRequest": None,
            }
        )

    fake_session.get = get_with_trace  # type: ignore[method-assign]
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    response = await Agent(environment=_CountingEnvironment()).run("return trace")

    assert response.execution_trace_context == execution_trace_context
    assert (
        response.model_dump(by_alias=True)["executionTraceContext"]
        == execution_trace_context
    )


@pytest.mark.asyncio
async def test_trace_context_manager_materializes_registered_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import narada.environment as environment_module

    trace_module = importlib.import_module("narada.tracing")

    execution_trace_context = {
        "type": "executionTraceContext",
        "label": "Trace",
        "traceId": "trace-1",
        "executionTraceS3Key": "user-test/recording-trace-1/execution-trace/index.json",
    }
    calls: list[dict[str, Any]] = []

    async def fake_materialize(context: dict[str, Any], **kwargs: Any) -> Any:
        calls.append({"context": context, **kwargs})

        class _Result:
            path = tmp_path / "proof"

        return _Result()

    fake_session = _RemoteDispatchFakeClientSession()

    def get_with_trace(url: str, **kwargs: Any) -> _FakeResponse:
        del kwargs
        if "/remote-dispatch/responses/" not in url:
            raise AssertionError(f"Unexpected GET URL: {url}")
        return _FakeResponse(
            {
                "status": "success",
                "response": {
                    "text": "ok",
                    "output": {"type": "text", "content": "ok"},
                    "executionTraceContext": execution_trace_context,
                },
                "usage": {"actions": 1, "credits": 1},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "activeInputRequest": None,
            }
        )

    fake_session.get = get_with_trace  # type: ignore[method-assign]
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )
    monkeypatch.setattr(
        trace_module, "materialize_execution_trace_context", fake_materialize
    )

    async with trace("unit-trace", out=tmp_path / "proof") as tr:
        response = await Agent(environment=_CountingEnvironment()).run("return trace")

    assert tr.path == tmp_path / "proof"
    assert response.execution_trace_path == str(tmp_path / "proof")
    assert calls[0]["context"] == execution_trace_context
    assert calls[0]["out"] == tmp_path / "proof"
    assert fake_session.dispatched_bodies[0]["captureExecutionTrace"] is True


@pytest.mark.asyncio
async def test_agent_run_trace_true_materializes_single_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import narada.agent as agent_module
    import narada.environment as environment_module

    execution_trace_context = {
        "type": "executionTraceContext",
        "label": "Trace",
        "traceId": "trace-1",
        "executionTraceS3Key": "user-test/recording-trace-1/execution-trace/index.json",
    }
    calls: list[dict[str, Any]] = []

    async def fake_materialize(context: dict[str, Any], **kwargs: Any) -> Any:
        calls.append({"context": context, **kwargs})

        class _Result:
            path = tmp_path / "proof"

        return _Result()

    fake_session = _RemoteDispatchFakeClientSession()

    def get_with_trace(url: str, **kwargs: Any) -> _FakeResponse:
        del kwargs
        if "/remote-dispatch/responses/" not in url:
            raise AssertionError(f"Unexpected GET URL: {url}")
        return _FakeResponse(
            {
                "status": "success",
                "response": {
                    "text": "ok",
                    "output": {"type": "text", "content": "ok"},
                    "executionTraceContext": execution_trace_context,
                },
                "usage": {"actions": 1, "credits": 1},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "activeInputRequest": None,
            }
        )

    fake_session.get = get_with_trace  # type: ignore[method-assign]
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )
    monkeypatch.setattr(
        agent_module, "materialize_execution_trace_context", fake_materialize
    )

    response = await Agent(environment=_CountingEnvironment()).run(
        "return trace", trace=True
    )

    assert response.execution_trace_path == str(tmp_path / "proof")
    assert calls[0]["context"] == execution_trace_context
    assert calls[0]["label"].startswith("agent-run-req-")
    assert fake_session.dispatched_bodies[0]["captureExecutionTrace"] is True


@pytest.mark.asyncio
async def test_agent_run_trace_true_inside_trace_context_materializes_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import narada.agent as agent_module
    import narada.environment as environment_module

    trace_module = importlib.import_module("narada.tracing")
    execution_trace_context = {
        "type": "executionTraceContext",
        "label": "Trace",
        "traceId": "trace-1",
        "executionTraceS3Key": "user-test/recording-trace-1/execution-trace/index.json",
    }
    agent_calls: list[dict[str, Any]] = []
    context_calls: list[dict[str, Any]] = []

    async def fake_agent_materialize(context: dict[str, Any], **kwargs: Any) -> Any:
        agent_calls.append({"context": context, **kwargs})

        class _Result:
            path = tmp_path / "agent-proof"

        return _Result()

    async def fake_context_materialize(context: dict[str, Any], **kwargs: Any) -> Any:
        context_calls.append({"context": context, **kwargs})

        class _Result:
            path = tmp_path / "context-proof"

        return _Result()

    fake_session = _RemoteDispatchFakeClientSession()

    def get_with_trace(url: str, **kwargs: Any) -> _FakeResponse:
        del kwargs
        if "/remote-dispatch/responses/" not in url:
            raise AssertionError(f"Unexpected GET URL: {url}")
        return _FakeResponse(
            {
                "status": "success",
                "response": {
                    "text": "ok",
                    "output": {"type": "text", "content": "ok"},
                    "executionTraceContext": execution_trace_context,
                },
                "usage": {"actions": 1, "credits": 1},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "activeInputRequest": None,
            }
        )

    fake_session.get = get_with_trace  # type: ignore[method-assign]
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )
    monkeypatch.setattr(
        agent_module, "materialize_execution_trace_context", fake_agent_materialize
    )
    monkeypatch.setattr(
        trace_module, "materialize_execution_trace_context", fake_context_materialize
    )

    async with trace("unit-trace", out=tmp_path / "context-proof") as tr:
        response = await Agent(environment=_CountingEnvironment()).run(
            "return trace",
            trace=True,
        )

    assert response.execution_trace_path == str(tmp_path / "agent-proof")
    assert tr.path is None
    assert len(agent_calls) == 1
    assert context_calls == []
    assert fake_session.dispatched_bodies[0]["captureExecutionTrace"] is True

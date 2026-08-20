from __future__ import annotations

from typing import Any

import pytest
from narada import Agent, AgentKind, Environment, ReasoningEffort


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
        self.response_trace: object | None = None

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
        response: dict[str, Any] = {
            "text": f"ok-{self._poll_count}",
            "output": {"type": "text", "content": f"ok-{self._poll_count}"},
        }
        if self.response_trace is not None:
            response["trace"] = self.response_trace
        return _FakeResponse(
            {
                "status": "success",
                "response": response,
                "usage": {"actions": 1, "credits": 1},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "hitlInputMetadata": None,
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
    assert all("reasoningMode" not in body for body in fake_session.dispatched_bodies)
    assert first.trace == []


@pytest.mark.asyncio
async def test_agent_run_parses_response_trace_records_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module
    from narada import AgentSpanData, Span, Trace

    fake_session = _RemoteDispatchFakeClientSession()
    fake_session.response_trace = [
        {
            "object": "trace",
            "trace_id": "trace_123",
            "name": "Operator",
            "group_id": None,
            "metadata": None,
        },
        {"object": "trace.span", "span_id": "invalid"},
        {
            "object": "trace.span",
            "span_id": "span_123",
            "trace_id": "trace_123",
            "parent_id": None,
            "started_at": "2026-07-29T12:00:00.000Z",
            "ended_at": "2026-07-29T12:00:01.000Z",
            "span_data": {
                "type": "agent",
                "name": "Operator",
                "agent_type": "operator",
                "prompt": "Find the Narada homepage",
                "response": "Done",
                "status": "success",
                "request_id": "req-1",
                "usage": None,
            },
            "error": None,
        },
    ]
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    response = await Agent(environment=_CountingEnvironment()).run("find homepage")

    assert len(response.trace) == 2
    assert isinstance(response.trace[0], Trace)
    assert isinstance(response.trace[1], Span)
    assert isinstance(response.trace[1].span_data, AgentSpanData)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "reasoning", "expected_prompt"),
    [
        (AgentKind.PRODUCTIVITY, ReasoningEffort.NONE, "analyze"),
        (AgentKind.OPERATOR, ReasoningEffort.LOW, "/Operator analyze"),
        (AgentKind.OPERATOR_MINI, ReasoningEffort.LOW, "/OperatorMini analyze"),
        (AgentKind.CORE_AGENT, ReasoningEffort.MEDIUM, "/coreAgent analyze"),
        (AgentKind.CORE_AGENT_MINI, ReasoningEffort.MEDIUM, "/CoreAgentMini analyze"),
    ],
)
async def test_agent_run_forwards_reasoning_for_every_agent_kind(
    monkeypatch: pytest.MonkeyPatch,
    kind: AgentKind | str,
    reasoning: ReasoningEffort,
    expected_prompt: str,
) -> None:
    import narada.environment as environment_module

    fake_session = _RemoteDispatchFakeClientSession()
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    await Agent(environment=_CountingEnvironment(), kind=kind).run(
        "analyze",
        reasoning=reasoning,
    )

    assert fake_session.dispatched_bodies[0]["prompt"] == expected_prompt
    assert fake_session.dispatched_bodies[0]["reasoningMode"] == reasoning.value


@pytest.mark.asyncio
async def test_agent_run_rejects_top_level_reasoning_for_named_agent() -> None:
    agent = Agent(environment=_CountingEnvironment(), kind="/owner/custom-agent")

    with pytest.raises(ValueError, match="named Agent Studio agents"):
        await agent.run("analyze", reasoning=ReasoningEffort.HIGH)


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
async def test_agent_run_sends_operator_mini_command_without_transport_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_session = _RemoteDispatchFakeClientSession()
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    await Agent(
        environment=_CountingEnvironment(),
        kind=AgentKind.OPERATOR_MINI,
    ).run("fast task")

    assert fake_session.dispatched_bodies[0]["prompt"] == "/OperatorMini fast task"
    assert "modelTier" not in fake_session.dispatched_bodies[0]

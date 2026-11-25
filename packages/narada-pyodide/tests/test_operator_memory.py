from __future__ import annotations

import asyncio
import builtins
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "memory_outcome", ["published", "failed", "timeout", "cancel", None]
)
async def test_operator_memory_uses_existing_browser_identity_and_preserves_result(
    pyodide_narada, monkeypatch, memory_outcome
):
    import narada.environment as environment

    monkeypatch.setattr(builtins, "_narada_request_id", "workflow", raising=False)
    monkeypatch.setenv(
        "NARADA_EXECUTION_TRACE_CONTEXT", json.dumps({"traceId": "workflow-trace"})
    )
    monkeypatch.setattr(
        environment,
        "_narada_get_id_token",
        AsyncMock(return_value="test"),
        raising=False,
    )
    monkeypatch.setattr(environment, "_parent_run_ids", lambda: ["workflow"])
    attempt = {
        "status": "success",
        "completedAt": "2026-11-24T00:00:00Z",
        "response": {
            "text": "six nightly rates",
            "output": {"type": "text", "content": "six nightly rates"},
        },
        "usage": {"actions": 1, "credits": 2},
    }
    monkeypatch.setattr(
        environment.Environment,
        "_validate_sdk_config",
        AsyncMock(),
    )
    poll = AsyncMock(
        return_value=SimpleNamespace(ok=True, json=AsyncMock(return_value=attempt))
    )
    monkeypatch.setattr(environment, "pyfetch_with_retries", poll)
    submit = SimpleNamespace(
        ok=True, json=AsyncMock(return_value={"requestId": "child"})
    )
    failure = {
        "timeout": TimeoutError,
        "cancel": asyncio.CancelledError,
    }.get(memory_outcome)
    finalize = SimpleNamespace(
        ok=True,
        json=AsyncMock(
            return_value={
                "outcome": memory_outcome,
                "usageIsFinal": True,
                "usage": {"actions": 1, "credits": 12},
            },
            side_effect=failure,
        ),
    )
    transport = AsyncMock(side_effect=[submit, finalize])
    monkeypatch.setattr(environment, "pyfetch", transport)
    browser = pyodide_narada.BrowserEnvironment(
        browser_window_id="window", user_id="user", env="dev"
    )
    agent = pyodide_narada.Agent(
        environment=browser, kind=pyodide_narada.AgentKind.OPERATOR
    )
    key = None if memory_outcome is None else "booking-rates"
    if memory_outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await agent.run("Read nightly rates", operator_memory_key=key)
    else:
        result = await agent.run("Read nightly rates", operator_memory_key=key)
        assert result.text == "six nightly rates"
        if memory_outcome is None:
            assert result.operator_memory is None
            assert "operator_memory" not in result.model_dump()
            assert result.usage.credits == 2
        else:
            assert result.operator_memory is not None
            assert result.operator_memory.outcome == (
                "unknown" if memory_outcome == "timeout" else memory_outcome
            )
            assert result.operator_memory.usage_is_final == (
                memory_outcome != "timeout"
            )
            assert result.usage.credits == (2 if memory_outcome == "timeout" else 12)

    [first, *rest] = transport.await_args_list
    assert first.kwargs["headers"]["Authorization"] == "Bearer test"
    assert first.kwargs["headers"]["X-Narada-User-ID"] == "user"
    assert first.kwargs["headers"]["X-Narada-Env"] == "dev"
    dispatch = json.loads(first.kwargs["body"])
    assert "memoryId" not in dispatch
    assert dispatch["parentRequestId"] == "workflow"
    assert dispatch["executionTraceContext"]["traceId"] == "workflow-trace"
    if key is None:
        assert "operatorMemoryKey" not in dispatch
        assert "requireExecutionTrace" not in dispatch
        assert rest == []
    else:
        assert dispatch["operatorMemoryKey"] == key
        assert dispatch["requireExecutionTrace"] is True
        [finalize_call] = rest
        assert finalize_call.args[0].endswith(
            "/responses/child/operator-memory/finalize"
        )
        assert finalize_call.kwargs["method"] == "POST"
        assert finalize_call.kwargs["headers"] == first.kwargs["headers"]


@pytest.mark.asyncio
async def test_memory_validation_happens_before_dispatch(pyodide_narada):
    environment = SimpleNamespace()
    operator = pyodide_narada.Agent(
        environment=environment, kind=pyodide_narada.AgentKind.OPERATOR
    )
    other = pyodide_narada.Agent(
        environment=environment, kind=pyodide_narada.AgentKind.CORE_AGENT
    )
    with pytest.raises(ValueError, match="letters"):
        await operator.run("Read nightly rates", operator_memory_key="a/b")
    with pytest.raises(ValueError, match="only supported"):
        await other.run("Read nightly rates", operator_memory_key="booking")
    with pytest.raises(ValueError, match="critic"):
        await operator.run(
            "Read nightly rates", operator_memory_key="booking", critic=object()
        )

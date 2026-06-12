from __future__ import annotations

from http import HTTPStatus
from typing import Any

import pytest
from narada import Agent, RemoteBrowserEnvironment
from narada_core.actions.models import (
    DEFAULT_HITL_TIMEOUT_SECONDS,
    PromptForUserInputVariable,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        self._payload = payload
        self.status = status

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = iter(responses)
        self.post_bodies: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, _url: str, **kwargs: Any) -> _FakeResponse:
        self.post_bodies.append(kwargs["json"])
        return _FakeResponse(next(self._responses))

    def get(self, _url: str, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(next(self._responses))


@pytest.mark.asyncio
async def test_agent_run_forwards_timeout_to_remote_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _FakeSession(
        [
            {"requestId": "request-123"},
            {
                "status": "success",
                "response": {
                    "text": "ok",
                    "output": {"type": "text", "content": "ok"},
                },
                "usage": {"actions": 0, "credits": 0},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "activeInputRequest": None,
            },
        ]
    )
    monkeypatch.setattr(
        "narada.environment.aiohttp.ClientSession", lambda: fake_session
    )
    agent = Agent(
        environment=RemoteBrowserEnvironment(
            browser_window_id="bw-1", api_key="test-key"
        )
    )

    response = await agent.run("hello", timeout=17)

    assert response.status == "success"
    assert fake_session.post_bodies[0]["timeout"] == 17


@pytest.mark.asyncio
async def test_prompt_for_user_input_uses_hitl_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _FakeSession(
        [
            {
                "status": "success",
                "data": '{"values_by_name":{"name":"Narada"}}',
            }
        ]
    )
    monkeypatch.setattr(
        "narada.environment.aiohttp.ClientSession", lambda: fake_session
    )
    agent = Agent(
        environment=RemoteBrowserEnvironment(
            browser_window_id="bw-1", api_key="test-key"
        )
    )

    values = await agent.prompt_for_user_input(
        step_id="input-step",
        variables=[
            PromptForUserInputVariable(name="name", type="string", required=True),
        ],
    )

    assert values == {"name": "Narada"}
    assert fake_session.post_bodies[0]["timeout"] == DEFAULT_HITL_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_user_approval_respects_explicit_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _FakeSession(
        [
            {
                "status": "success",
                "data": '{"approved":true}',
            }
        ]
    )
    monkeypatch.setattr(
        "narada.environment.aiohttp.ClientSession", lambda: fake_session
    )
    agent = Agent(
        environment=RemoteBrowserEnvironment(
            browser_window_id="bw-1", api_key="test-key"
        )
    )

    approved = await agent.user_approval(
        step_id="approval-step",
        prompt_message="Proceed?",
        approve_label="Approve",
        reject_label="Reject",
        timeout=600,
    )

    assert approved is True
    assert fake_session.post_bodies[0]["timeout"] == 600


@pytest.mark.asyncio
async def test_execute_javascript_on_page_dispatches_extension_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _FakeSession(
        [
            {
                "status": "success",
                "data": '{"result":{"title":"Example Domain","count":3}}',
            }
        ]
    )
    monkeypatch.setattr(
        "narada.environment.aiohttp.ClientSession", lambda: fake_session
    )
    agent = Agent(
        environment=RemoteBrowserEnvironment(
            browser_window_id="bw-1", api_key="test-key"
        )
    )

    result = await agent.execute_javascript_on_page(
        code="(() => ({ title: document.title, count: 3 }))()",
    )

    assert result == {"title": "Example Domain", "count": 3}
    assert fake_session.post_bodies[0]["action"] == {
        "name": "execute_javascript_on_page",
        "code": "(() => ({ title: document.title, count: 3 }))()",
    }

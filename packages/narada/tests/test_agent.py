from __future__ import annotations

from typing import Any

import pytest
from narada import Agent, Environment


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

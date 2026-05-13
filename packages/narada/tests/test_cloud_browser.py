from __future__ import annotations

from typing import Any

import narada.client as client_module
import pytest
from narada import Narada


class _FakeResponse:
    ok = True
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def json(self) -> dict[str, Any]:
        return self._payload

    async def text(self) -> str:
        return ""


class _FakeClientSession:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.posts: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeClientSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append({"url": url, **kwargs})
        return _FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_extensionless_cloud_browser_uses_backend_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _FakeClientSession(
        {
            "session_id": "session-123",
            "session_name": "fast-session",
            "browser_window_id": "browser-window-123",
        }
    )
    monkeypatch.setattr(client_module.aiohttp, "ClientSession", lambda: fake_session)

    async def fail_if_client_initializes(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "extensionless cloud sessions should initialize server-side"
        )

    narada = Narada(auth_headers={"x-api-key": "test-key"})
    monkeypatch.setattr(
        narada, "_initialize_cloud_browser_window", fail_if_client_initializes
    )

    window = await narada.open_and_initialize_cloud_browser_window(
        session_name="fast-session",
        session_timeout=300,
        require_extension=False,
    )

    assert window.browser_window_id == "browser-window-123"
    assert window.cloud_browser_session_id == "session-123"
    assert len(fake_session.posts) == 1
    post = fake_session.posts[0]
    assert post["url"].endswith(
        "/cloud-browser/create-and-initialize-cloud-browser-session"
    )
    assert post["headers"] == {"x-api-key": "test-key"}
    assert post["json"] == {
        "require_extension": False,
        "session_name": "fast-session",
        "session_timeout": 300,
    }


class _ForbiddenResponse:
    ok = False
    status = 403

    async def __aenter__(self) -> "_ForbiddenResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def json(self) -> dict[str, Any]:
        return {}

    async def text(self) -> str:
        return '{"detail": {"reason": "forbidden"}}'


class _ForbiddenClientSession:
    def __init__(self) -> None:
        self.posts: list[str] = []

    async def __aenter__(self) -> "_ForbiddenClientSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def post(self, url: str, **kwargs: Any) -> _ForbiddenResponse:
        self.posts.append(url)
        return _ForbiddenResponse()


@pytest.mark.asyncio
async def test_extensionless_cloud_browser_forbidden_sets_error_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _ForbiddenClientSession()
    monkeypatch.setattr(client_module.aiohttp, "ClientSession", lambda: fake_session)

    narada = Narada(auth_headers={"x-api-key": "test-key"})

    with pytest.raises(RuntimeError) as excinfo:
        await narada.open_and_initialize_cloud_browser_window(require_extension=False)

    err = excinfo.value
    assert getattr(err, "status_code", None) == 403
    assert getattr(err, "detail", None) == {"reason": "forbidden"}
    assert len(fake_session.posts) == 1
    assert fake_session.posts[0].endswith(
        "/cloud-browser/create-and-initialize-cloud-browser-session"
    )

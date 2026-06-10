from __future__ import annotations

import narada.environment as environment_module
import pytest
from narada import CloudBrowserEnvironment, RemoteBrowserEnvironment
from narada.config import BrowserConfig


class _FakePage:
    def __init__(self) -> None:
        self.goto_calls: list[dict[str, object]] = []
        self.url = "about:blank"

    async def goto(self, url: str, **kwargs: object) -> None:
        self.url = url
        self.goto_calls.append({"url": url, **kwargs})


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self.pages = [page]


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self.contexts = [_FakeContext(page)]
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class _FakeChromium:
    def __init__(self, page: _FakePage) -> None:
        self.browser = _FakeBrowser(page)

    async def connect_over_cdp(
        self, cdp_websocket_url: str, *, headers: dict[str, str]
    ) -> _FakeBrowser:
        return self.browser


class _FakePlaywright:
    def __init__(self, page: _FakePage) -> None:
        self.chromium = _FakeChromium(page)


class _FakeRemoteDispatchPostResponse:
    ok = True
    status = 200

    async def __aenter__(self) -> _FakeRemoteDispatchPostResponse:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> dict[str, object]:
        return {"requestId": "request-123"}


class _FakeRemoteDispatchGetResponse:
    ok = True
    status = 200

    async def __aenter__(self) -> _FakeRemoteDispatchGetResponse:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> dict[str, object]:
        return {
            "status": "success",
            "response": {
                "text": "done",
                "output": None,
                "executionTraceContext": {
                    "type": "executionTraceContext",
                    "executionTraceS3Key": "user-test/execution-trace/index.json",
                },
            },
            "createdAt": "2026-06-03T00:00:00Z",
            "completedAt": "2026-06-03T00:00:01Z",
            "usage": {"actions": 1, "credits": 0.1},
        }


class _FakeRemoteDispatchSession:
    post_calls: list[dict[str, object]] = []
    get_calls: list[dict[str, object]] = []

    async def __aenter__(self) -> _FakeRemoteDispatchSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> _FakeRemoteDispatchPostResponse:
        self.post_calls.append({"url": url, **kwargs})
        return _FakeRemoteDispatchPostResponse()

    def get(self, url: str, **kwargs: object) -> _FakeRemoteDispatchGetResponse:
        self.get_calls.append({"url": url, **kwargs})
        return _FakeRemoteDispatchGetResponse()


@pytest.mark.asyncio
async def test_cloud_browser_initialization_uses_domcontentloaded_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    env = CloudBrowserEnvironment(
        config=BrowserConfig(interactive=False),
        auth_headers={"x-test": "true"},
    )
    env._playwright = _FakePlaywright(page)

    async def wait_for_browser_window_id(*args: object, **kwargs: object) -> str:
        return "window-123"

    async def wait_for_cloud_side_panel_page(
        *args: object, **kwargs: object
    ) -> _FakePage:
        side_panel_page = _FakePage()
        side_panel_page.url = "chrome-extension://dev-extension/sidepanel.html"
        side_panel_page.context = _FakeContext(side_panel_page)
        return side_panel_page

    monkeypatch.setattr(
        env, "_wait_for_cloud_browser_window_id", wait_for_browser_window_id
    )
    monkeypatch.setattr(
        env, "_wait_for_cloud_side_panel_page", wait_for_cloud_side_panel_page
    )

    await env._initialize_cloud_browser_window(
        cdp_websocket_url="wss://example.test/cdp",
        session_id="session-123",
        login_url="https://example.test/initialize",
        cdp_auth_headers={"authorization": "Bearer test"},
    )

    assert env.browser_window_id == "window-123"
    assert env.cloud_browser_session_id == "session-123"
    assert page.goto_calls == [
        {
            "url": "https://example.test/initialize",
            "timeout": 15_000,
            "wait_until": "domcontentloaded",
        }
    ]


@pytest.mark.asyncio
async def test_remote_dispatch_forwards_managed_cloud_browser_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeRemoteDispatchSession.post_calls = []
    _FakeRemoteDispatchSession.get_calls = []
    monkeypatch.setenv("NARADA_API_BASE_URL", "https://api.example.test/fast/v2")
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", _FakeRemoteDispatchSession
    )

    env = RemoteBrowserEnvironment(
        browser_window_id="sdk-managed-cloud-browser",
        cloud_browser_session_id="cloud-session-123",
        auth_headers={"x-test": "true"},
    )

    response = await env._dispatch_request(
        prompt="Fill the RPA challenge form.",
        timeout=30,
    )

    assert response["response"] is not None
    assert response["response"]["executionTraceContext"] == {
        "type": "executionTraceContext",
        "executionTraceS3Key": "user-test/execution-trace/index.json",
    }
    assert len(_FakeRemoteDispatchSession.post_calls) == 1
    post_call = _FakeRemoteDispatchSession.post_calls[0]
    assert post_call["url"] == "https://api.example.test/fast/v2/remote-dispatch"
    assert post_call["headers"] == {"x-test": "true"}
    assert post_call["json"] == {
        "prompt": "/Operator Fill the RPA challenge form.",
        "browserWindowId": "sdk-managed-cloud-browser",
        "timeZone": "America/Los_Angeles",
        "cloudBrowserSessionId": "cloud-session-123",
    }

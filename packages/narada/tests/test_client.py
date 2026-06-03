from __future__ import annotations

import pytest
from narada import window as window_module
from narada.client import Narada
from narada.config import BrowserConfig
from narada.window import RemoteBrowserWindow


class _FakePage:
    def __init__(self) -> None:
        self.goto_calls: list[dict[str, object]] = []

    async def goto(self, url: str, **kwargs: object) -> None:
        self.goto_calls.append({"url": url, **kwargs})


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self.pages = [page]


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self.contexts = [_FakeContext(page)]


class _FakeChromium:
    def __init__(self, page: _FakePage) -> None:
        self.page = page

    async def connect_over_cdp(
        self, cdp_websocket_url: str, *, headers: dict[str, str]
    ) -> _FakeBrowser:
        return _FakeBrowser(self.page)


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
    narada = Narada(auth_headers={"x-test": "true"})
    narada._playwright = _FakePlaywright(page)

    async def wait_for_browser_window_id(*args: object, **kwargs: object) -> str:
        return "window-123"

    monkeypatch.setattr(
        narada, "_wait_for_browser_window_id", wait_for_browser_window_id
    )

    window = await narada._initialize_cloud_browser_window(
        config=BrowserConfig(interactive=False),
        cdp_websocket_url="wss://example.test/cdp",
        session_id="session-123",
        login_url="https://example.test/initialize",
        cdp_auth_headers={"authorization": "Bearer test"},
    )

    assert window.browser_window_id == "window-123"
    assert page.goto_calls == [
        {
            "url": "https://example.test/initialize",
            "timeout": 60_000,
            "wait_until": "domcontentloaded",
        }
    ]


@pytest.mark.asyncio
async def test_remote_dispatch_forwards_managed_cloud_browser_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeRemoteDispatchSession.post_calls = []
    _FakeRemoteDispatchSession.get_calls = []
    monkeypatch.setenv("NARADA_API_BASE_URL", "https://api.example.test/fast/v2")
    monkeypatch.setattr(window_module.aiohttp, "ClientSession", _FakeRemoteDispatchSession)

    window = RemoteBrowserWindow(
        browser_window_id="sdk-managed-cloud-browser",
        auth_headers={"x-test": "true"},
    )

    response = await window.dispatch_request(
        prompt="Fill the RPA challenge form.",
        execution_mode="cloud_browser",
        cloud_browser_session_name="proof-session",
        cloud_browser_app_origin_override="https://proof.example.test",
        cloud_browser_extension_s3_bucket="narada-chrome-extension-test-builds",
        cloud_browser_extension_s3_key="proof/branch-extension.zip",
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
        "executionMode": "cloud_browser",
        "cloudBrowserSessionName": "proof-session",
        "cloudBrowserAppOriginOverride": "https://proof.example.test",
        "cloudBrowserExtensionS3Bucket": "narada-chrome-extension-test-builds",
        "cloudBrowserExtensionS3Key": "proof/branch-extension.zip",
    }

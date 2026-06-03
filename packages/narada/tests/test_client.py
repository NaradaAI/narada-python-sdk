from __future__ import annotations

import pytest
from narada.client import Narada
from narada.config import BrowserConfig


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

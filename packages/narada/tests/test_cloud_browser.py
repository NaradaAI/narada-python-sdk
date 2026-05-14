from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from narada.client import Narada
from narada.config import BrowserConfig
from narada_core.errors import NaradaTimeoutError


def _build_client_with_cloud_page(page: AsyncMock) -> Narada:
    client = Narada(auth_headers={"x-api-key": "test-key"})
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])])
    client._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser))
    )
    return client


@pytest.mark.asyncio
async def test_initialize_cloud_browser_window_uses_domcontentloaded_for_login_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    client = _build_client_with_cloud_page(page)

    wait_for_browser_window_id = AsyncMock(return_value="browser-window-123")
    monkeypatch.setattr(
        client, "_wait_for_browser_window_id", wait_for_browser_window_id
    )

    window = await client._initialize_cloud_browser_window(
        config=BrowserConfig(interactive=False),
        cdp_websocket_url="wss://agentcore.example.test/session-123",
        session_id="session-123",
        login_url="https://app.narada.ai/chat?customToken=test-token",
        cdp_auth_headers={"Authorization": "signed-cdp"},
    )

    page.goto.assert_awaited_once_with(
        "https://app.narada.ai/chat?customToken=test-token",
        timeout=15_000,
        wait_until="domcontentloaded",
    )
    wait_for_browser_window_id.assert_awaited_once_with(
        page,
        BrowserConfig(interactive=False),
        timeout=30_000,
    )
    assert window.browser_window_id == "browser-window-123"
    assert window.cloud_browser_session_id == "session-123"


@pytest.mark.asyncio
async def test_initialize_cloud_browser_window_uses_domcontentloaded_for_retry_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    client = _build_client_with_cloud_page(page)

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaTimeoutError("Timed out waiting for browser window ID"),
            "browser-window-123",
        ]
    )
    monkeypatch.setattr(
        client, "_wait_for_browser_window_id", wait_for_browser_window_id
    )

    window = await client._initialize_cloud_browser_window(
        config=BrowserConfig(interactive=False),
        cdp_websocket_url="wss://agentcore.example.test/session-123",
        session_id="session-123",
        login_url="https://app.narada.ai/chat?customToken=test-token",
        cdp_auth_headers={"Authorization": "signed-cdp"},
    )

    assert page.goto.await_args_list == [
        call(
            "https://app.narada.ai/chat?customToken=test-token",
            timeout=15_000,
            wait_until="domcontentloaded",
        ),
        call(
            "https://app.narada.ai/chat?customToken=test-token",
            timeout=15_000,
            wait_until="domcontentloaded",
        ),
    ]
    assert wait_for_browser_window_id.await_count == 2
    assert window.browser_window_id == "browser-window-123"

from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import narada.client as client_module
import pytest
from narada.client import Narada
from narada.config import BrowserConfig
from narada.window import (
    CloudBrowserWindow,
    RemoteBrowserWindow,
    create_side_panel_url,
)
from narada_core.errors import NaradaTimeoutError


class _FakeResponse:
    ok = True
    status = 200

    def __init__(self, payload: dict, *args, **kwargs) -> None:
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        return None

    async def json(self):
        return self._payload

    async def text(self):
        return ""


class _FakeClientSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, url: str, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return _FakeResponse(self.payload)


class _RemoteDispatchFakeClientSession:
    def __init__(self, poll_payloads: list[dict]) -> None:
        self.poll_payloads = poll_payloads
        self.dispatched_body: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, url: str, **kwargs):
        if url.endswith("/remote-dispatch"):
            self.dispatched_body = kwargs["json"]
            return _FakeResponse({"requestId": "req-123"})
        raise AssertionError(f"Unexpected POST URL: {url}")

    def get(self, url: str, **kwargs):
        if url.endswith("/remote-dispatch/responses/req-123"):
            return _FakeResponse(self.poll_payloads.pop(0))
        raise AssertionError(f"Unexpected GET URL: {url}")


def _fake_browser_with_pages(pages: list[object]) -> SimpleNamespace:
    return SimpleNamespace(
        contexts=[SimpleNamespace(pages=pages)],
        close=AsyncMock(),
    )


def _fake_side_panel_page(
    browser_window_id: str = "browser-window-123",
) -> SimpleNamespace:
    return SimpleNamespace(
        url=create_side_panel_url(BrowserConfig(interactive=False), browser_window_id)
    )


def _build_client_with_cloud_page(page: AsyncMock) -> Narada:
    client = Narada(auth_headers={"x-api-key": "test-key"})
    page.url = "about:blank"
    browser = _fake_browser_with_pages([page, _fake_side_panel_page()])
    client._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser))
    )
    return client


@pytest.mark.asyncio
async def test_dispatch_request_calls_input_required_callback_once_per_input_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.window as window_module

    fake_session = _RemoteDispatchFakeClientSession(
        [
            {
                "status": "input-required",
                "response": None,
                "usage": None,
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": None,
                "activeInputRequest": {
                    "inputId": "input-1",
                    "action": {
                        "name": "prompt_for_user_input",
                        "step_id": "prompt-1",
                        "variables": [
                            {"name": "email", "type": "string", "required": True}
                        ],
                    },
                },
            },
            {
                "status": "input-required",
                "response": None,
                "usage": None,
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": None,
                "activeInputRequest": {
                    "inputId": "input-1",
                    "action": {
                        "name": "prompt_for_user_input",
                        "step_id": "prompt-1",
                        "variables": [
                            {"name": "email", "type": "string", "required": True}
                        ],
                    },
                },
            },
            {
                "status": "input-required",
                "response": None,
                "usage": None,
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": None,
                "activeInputRequest": {
                    "inputId": "input-2",
                    "action": {
                        "name": "user_approval",
                        "step_id": "approval-1",
                        "prompt_message": "Approve?",
                        "approve_label": "Approve",
                        "reject_label": "Reject",
                    },
                },
            },
            {
                "status": "success",
                "response": {"text": "ok"},
                "usage": {"actions": 1, "credits": 1},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "activeInputRequest": None,
            },
        ]
    )
    monkeypatch.setattr(window_module.aiohttp, "ClientSession", lambda: fake_session)
    sleep = AsyncMock()
    monkeypatch.setattr(window_module.asyncio, "sleep", sleep)

    observed_input_ids: list[str] = []

    async def on_input_required(active_input_request) -> None:
        observed_input_ids.append(active_input_request.input_id)

    window = RemoteBrowserWindow(browser_window_id="bw-1", api_key="test-key")

    response = await window.dispatch_request(
        prompt="Summarize",
        timeout=5,
        on_input_required=on_input_required,
    )

    assert response["status"] == "success"
    assert observed_input_ids == ["input-1", "input-2"]
    assert sleep.await_count == 3


@pytest.mark.asyncio
async def test_extensionless_cloud_browser_uses_backend_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.client as client_module

    fake_session = _FakeClientSession(
        {
            "session_id": "session-123",
            "session_name": "fast-session",
            "browser_window_id": "browser-window-123",
        }
    )
    monkeypatch.setattr(client_module.aiohttp, "ClientSession", lambda: fake_session)

    async def fail_if_client_initializes(*args, **kwargs):
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
        timeout=60_000,
        wait_until="domcontentloaded",
    )
    wait_for_browser_window_id.assert_awaited_once_with(
        page,
        BrowserConfig(interactive=False),
        timeout=30_000,
    )
    assert window.browser_window_id == "browser-window-123"
    assert window.cloud_browser_session_id == "session-123"
    client._playwright.chromium.connect_over_cdp.return_value.close.assert_not_awaited()


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
            timeout=60_000,
            wait_until="domcontentloaded",
        ),
        call(
            "https://app.narada.ai/chat?customToken=test-token",
            timeout=60_000,
            wait_until="domcontentloaded",
        ),
    ]
    assert wait_for_browser_window_id.await_count == 2
    assert window.browser_window_id == "browser-window-123"
    client._playwright.chromium.connect_over_cdp.return_value.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_browser_side_panel_readiness_uses_visible_page_without_reconnect() -> None:
    client = Narada(auth_headers={"x-api-key": "test-key"})
    browser = _fake_browser_with_pages([_fake_side_panel_page()])
    client._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock())
    )

    await client._ensure_cloud_browser_side_panel_page(
        browser=browser,
        config=BrowserConfig(interactive=False),
        browser_window_id="browser-window-123",
        cdp_websocket_url="wss://agentcore.example.test/session-123",
        cdp_auth_headers={"Authorization": "signed-cdp"},
    )

    browser.close.assert_not_awaited()
    client._playwright.chromium.connect_over_cdp.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_browser_side_panel_readiness_can_appear_after_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Narada(auth_headers={"x-api-key": "test-key"})
    first_browser = _fake_browser_with_pages([])
    second_browser = _fake_browser_with_pages([_fake_side_panel_page()])
    client._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=second_browser))
    )
    sleep = AsyncMock()
    monkeypatch.setattr(client_module.asyncio, "sleep", sleep)

    await client._ensure_cloud_browser_side_panel_page(
        browser=first_browser,
        config=BrowserConfig(interactive=False),
        browser_window_id="browser-window-123",
        cdp_websocket_url="wss://agentcore.example.test/session-123",
        cdp_auth_headers={"Authorization": "signed-cdp"},
    )

    first_browser.close.assert_awaited_once()
    sleep.assert_awaited_once_with(1)
    client._playwright.chromium.connect_over_cdp.assert_awaited_once_with(
        "wss://agentcore.example.test/session-123",
        headers={"Authorization": "signed-cdp"},
    )
    second_browser.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_browser_side_panel_readiness_times_out_when_page_never_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Narada(auth_headers={"x-api-key": "test-key"})
    first_browser = _fake_browser_with_pages([])
    reconnect_browser = _fake_browser_with_pages([])
    client._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=reconnect_browser))
    )
    sleep = AsyncMock()
    monkeypatch.setattr(client_module.asyncio, "sleep", sleep)

    with pytest.raises(NaradaTimeoutError):
        await client._ensure_cloud_browser_side_panel_page(
            browser=first_browser,
            config=BrowserConfig(interactive=False),
            browser_window_id="browser-window-123",
            cdp_websocket_url="wss://agentcore.example.test/session-123",
            cdp_auth_headers={"Authorization": "signed-cdp"},
        )

    assert sleep.await_count == 4
    assert client._playwright.chromium.connect_over_cdp.await_count == 4


@pytest.mark.asyncio
async def test_window_agent_exposes_workflow_trace_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_trace = {"step_type": "workflow", "children": []}
    window = CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        auth_headers={"x-api-key": "test-key"},
    )
    monkeypatch.setattr(
        window,
        "dispatch_request",
        AsyncMock(
            return_value={
                "requestId": "request-123",
                "status": "success",
                "response": {
                    "text": "done",
                    "output": {"type": "text", "content": "done"},
                    "workflowTrace": workflow_trace,
                },
                "completedAt": "2026-01-01T00:00:01Z",
                "usage": {"actions": 0, "credits": 0},
                "activeInputRequest": None,
            }
        ),
    )

    response = await window.agent(prompt="return a trace")

    assert response.workflow_trace == workflow_trace
    assert response.model_dump(by_alias=True)["workflowTrace"] == workflow_trace

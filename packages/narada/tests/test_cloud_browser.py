from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from narada.client import Narada
from narada.config import BrowserConfig
from narada.window import RemoteBrowserWindow
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


def _build_client_with_cloud_page(page: AsyncMock) -> Narada:
    client = Narada(auth_headers={"x-api-key": "test-key"})
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])])
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

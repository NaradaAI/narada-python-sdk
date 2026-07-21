import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from narada import (
    Agent,
    CloudBrowserEnvironment,
    LambdaEnvironment,
    RemoteBrowserEnvironment,
)
from narada.config import BrowserConfig
from narada.environment import create_side_panel_url
from narada_core.errors import NaradaInitializationError, NaradaTimeoutError


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


def _build_cloud_environment_with_page(page: AsyncMock) -> CloudBrowserEnvironment:
    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    page.add_init_script = AsyncMock()
    browser = SimpleNamespace(
        contexts=[SimpleNamespace(pages=[page], add_init_script=AsyncMock())]
    )
    env._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser))
    )
    return env


@pytest.mark.asyncio
async def test_dispatch_request_calls_input_required_callback_once_per_input_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_session = _RemoteDispatchFakeClientSession(
        [
            {
                "status": "input-required",
                "response": None,
                "usage": None,
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": None,
                "hitlInputMetadata": {
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
                "hitlInputMetadata": {
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
                "hitlInputMetadata": {
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
                "hitlInputMetadata": None,
            },
        ]
    )
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    observed_input_ids: list[str] = []

    async def on_input_required(hitl_input_metadata) -> None:
        observed_input_ids.append(hitl_input_metadata.input_id)

    env = RemoteBrowserEnvironment(browser_window_id="bw-1", api_key="test-key")

    response = await env._dispatch_request(
        prompt="Summarize",
        timeout=5,
        on_input_required=on_input_required,
    )

    assert response["status"] == "success"
    assert observed_input_ids == ["input-1", "input-2"]
    assert sleep.await_count == 3


@pytest.mark.asyncio
async def test_dispatch_request_includes_execution_trace_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    trace_context = {
        "type": "executionTraceInheritanceContext",
        "schemaVersion": 1,
        "traceId": "trace-parent",
        "parentSegmentId": "segment-local",
    }
    monkeypatch.setenv("NARADA_EXECUTION_TRACE_CONTEXT", json.dumps(trace_context))
    fake_session = _RemoteDispatchFakeClientSession(
        [
            {
                "status": "success",
                "response": {"text": "ok"},
                "usage": {"actions": 1, "credits": 1},
                "createdAt": "2026-01-01T00:00:00Z",
                "completedAt": "2026-01-01T00:00:01Z",
                "hitlInputMetadata": None,
            }
        ]
    )
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    env = RemoteBrowserEnvironment(browser_window_id="bw-1", api_key="test-key")
    response = await env._dispatch_request(prompt="Summarize", timeout=5)

    assert response["status"] == "success"
    assert fake_session.dispatched_body is not None
    assert fake_session.dispatched_body["executionTraceContext"] == trace_context


@pytest.mark.asyncio
async def test_extension_action_request_includes_action_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_session = _FakeClientSession({"status": "success", "data": None})
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    env = RemoteBrowserEnvironment(browser_window_id="bw-1", api_key="test-key")
    await env.close()

    assert fake_session.posts
    action_execution_id = fake_session.posts[0]["json"]["actionExecutionId"]
    assert action_execution_id.startswith("action_")


@pytest.mark.asyncio
async def test_remote_browser_environment_with_cloud_session_stops_session_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    stop_cloud_browser_session = AsyncMock()
    monkeypatch.setattr(
        environment_module,
        "_stop_cloud_browser_session",
        stop_cloud_browser_session,
    )

    env = RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        auth_headers={"x-api-key": "test-key"},
    )

    await env.close()

    stop_cloud_browser_session.assert_awaited_once_with(
        base_url=env._base_url,
        auth_headers={"x-api-key": "test-key"},
        session_id="session-123",
        timeout=None,
    )


@pytest.mark.asyncio
async def test_cloud_browser_environment_start_auto_detaches_after_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    browser = AsyncMock()
    playwright_context_manager = SimpleNamespace(__aexit__=AsyncMock())
    context = SimpleNamespace()

    async def initialize_once() -> None:
        env._session_id = "session-123"
        env._browser_window_id = "browser-window-123"
        env._cdp_websocket_url = "wss://agentcore.example.test/session-123"
        env._playwright_browser = browser
        env._context = context
        env._playwright_context_manager = playwright_context_manager
        env._playwright = object()

    monkeypatch.setattr(env, "_validate_sdk_config", AsyncMock())
    monkeypatch.setattr(env, "_initialize_once", initialize_once)

    await env.start()

    browser.close.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env.browser_window_id == "browser-window-123"
    assert env.cloud_browser_session_id == "session-123"
    assert env._cdp_websocket_url == "wss://agentcore.example.test/session-123"
    assert env._initialized is True
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_cloud_browser_environment_start_cleans_up_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    stop_cloud_browser_session = AsyncMock()
    monkeypatch.setattr(
        environment_module,
        "_stop_cloud_browser_session",
        stop_cloud_browser_session,
    )

    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    browser = AsyncMock()
    playwright_context_manager = SimpleNamespace(__aexit__=AsyncMock())
    initialize_calls = 0

    async def initialize_once() -> None:
        nonlocal initialize_calls
        initialize_calls += 1
        env._session_id = "session-123"
        env._browser_window_id = "browser-window-123"
        env._cdp_websocket_url = "wss://agentcore.example.test/session-123"
        env._playwright_browser = browser
        env._context = SimpleNamespace()
        env._playwright_context_manager = playwright_context_manager
        env._playwright = object()
        raise asyncio.CancelledError

    monkeypatch.setattr(env, "_initialize_once", initialize_once)

    with pytest.raises(asyncio.CancelledError):
        await env._initialize()

    assert initialize_calls == 1
    stop_cloud_browser_session.assert_awaited_once_with(
        base_url=env._base_url,
        auth_headers={"x-api-key": "test-key"},
        session_id="session-123",
        status="failed",
        timeout=10,
    )
    browser.close.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env._session_id is None
    assert env._browser_window_id is None
    assert env._cdp_websocket_url is None
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_cloud_browser_environment_detach_releases_playwright_without_stopping_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    stop_cloud_browser_session = AsyncMock()
    monkeypatch.setattr(
        environment_module,
        "_stop_cloud_browser_session",
        stop_cloud_browser_session,
    )

    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    env._initialized = True
    env._session_id = "session-123"
    env._browser_window_id = "browser-window-123"
    browser = AsyncMock()
    playwright_context_manager = SimpleNamespace(__aexit__=AsyncMock())
    env._playwright_browser = browser
    env._context = SimpleNamespace()
    env._playwright_context_manager = playwright_context_manager
    env._playwright = object()

    await env._detach()
    await env._detach()

    stop_cloud_browser_session.assert_not_awaited()
    browser.close.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env.browser_window_id == "browser-window-123"
    assert env.cloud_browser_session_id == "session-123"
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_cloud_browser_environment_reset_agent_state_reconnects_after_detach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    config = BrowserConfig(interactive=False)
    env = CloudBrowserEnvironment(auth_headers={"x-api-key": "test-key"}, config=config)
    env._initialized = True
    env._session_id = "session-123"
    env._browser_window_id = "browser-window-123"
    env._cdp_websocket_url = "wss://agentcore.example.test/session-123"
    fake_session = _FakeClientSession(
        {
            "auth_headers": {"Authorization": "fresh-cdp"},
            "cloud_browser_session_id": "session-123",
        }
    )
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    page = SimpleNamespace(
        url=create_side_panel_url(config, "browser-window-123"),
        reload=AsyncMock(),
    )
    browser = SimpleNamespace(
        contexts=[SimpleNamespace(pages=[page])],
        close=AsyncMock(),
    )
    connect_over_cdp = AsyncMock(return_value=browser)
    playwright_context_manager = SimpleNamespace(__aexit__=AsyncMock())

    async def start_playwright() -> None:
        env._playwright_context_manager = playwright_context_manager
        env._playwright = SimpleNamespace(
            chromium=SimpleNamespace(connect_over_cdp=connect_over_cdp)
        )

    monkeypatch.setattr(env, "_start_playwright", start_playwright)

    await env.reset_agent_state()

    connect_over_cdp.assert_awaited_once_with(
        "wss://agentcore.example.test/session-123",
        headers={"Authorization": "fresh-cdp"},
    )
    assert len(fake_session.posts) == 1
    post = fake_session.posts[0]
    assert post["url"].endswith("/cloud-browser/generate-cdp-auth-headers")
    assert post["headers"] == {"x-api-key": "test-key"}
    assert post["json"] == {
        "cdp_websocket_url": "wss://agentcore.example.test/session-123"
    }
    page.reload.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env.browser_window_id == "browser-window-123"
    assert env.cloud_browser_session_id == "session-123"
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_cloud_browser_environment_rejects_auth_headers_for_another_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    env._session_id = "session-123"
    env._cdp_websocket_url = "wss://agentcore.example.test/session-123"
    fake_session = _FakeClientSession(
        {
            "auth_headers": {"Authorization": "wrong-session"},
            "cloud_browser_session_id": "session-456",
        }
    )
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    with pytest.raises(NaradaInitializationError, match="session-456"):
        await env._generate_cdp_auth_headers()


@pytest.mark.asyncio
async def test_cloud_browser_environment_reset_cleans_up_when_reconnect_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    env._initialized = True
    env._session_id = "session-123"
    env._browser_window_id = "browser-window-123"
    env._cdp_websocket_url = "wss://agentcore.example.test/session-123"
    reconnect_started = asyncio.Event()
    playwright_context_manager = SimpleNamespace(__aexit__=AsyncMock())

    async def start_playwright() -> None:
        env._playwright_context_manager = playwright_context_manager
        env._playwright = object()

    async def connect_playwright_browser() -> None:
        reconnect_started.set()
        await asyncio.Future()

    monkeypatch.setattr(env, "_start_playwright", start_playwright)
    monkeypatch.setattr(env, "_connect_playwright_browser", connect_playwright_browser)

    reset_task = asyncio.create_task(env.reset_agent_state())
    await reconnect_started.wait()
    reset_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await reset_task

    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_cloud_browser_environment_close_stops_session_before_detaching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    events: list[str] = []

    async def stop_cloud_session(**kwargs: object) -> None:
        events.append("stop-session")

    async def close_browser() -> None:
        events.append("close-browser")

    async def stop_playwright(*args: object) -> None:
        events.append("stop-playwright")

    stop_cloud_browser_session = AsyncMock(side_effect=stop_cloud_session)
    monkeypatch.setattr(
        environment_module,
        "_stop_cloud_browser_session",
        stop_cloud_browser_session,
    )

    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    env._initialized = True
    env._session_id = "session-123"
    env._browser_window_id = "browser-window-123"
    env._playwright_browser = SimpleNamespace(
        close=AsyncMock(side_effect=close_browser)
    )
    env._context = SimpleNamespace()
    env._playwright_context_manager = SimpleNamespace(
        __aexit__=AsyncMock(side_effect=stop_playwright)
    )
    env._playwright = object()

    await env.close(timeout=7)

    stop_cloud_browser_session.assert_awaited_once_with(
        base_url=env._base_url,
        auth_headers={"x-api-key": "test-key"},
        session_id="session-123",
        timeout=7,
    )
    assert events == ["stop-session", "close-browser", "stop-playwright"]
    assert env.cloud_browser_session_id == "session-123"
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_lambda_environment_uses_backend_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_session = _FakeClientSession(
        {
            "session_id": "session-123",
            "session_name": "fast-session",
            "browser_window_id": "browser-window-123",
        }
    )
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )

    env = LambdaEnvironment(
        auth_headers={"x-api-key": "test-key"},
        session_name="fast-session",
        session_timeout=300,
    )
    await env.start()

    assert env.session_id == "session-123"
    assert env.cloud_browser_session_id == "session-123"
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
async def test_lambda_environment_exposes_downloaded_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    downloaded_files = [
        environment_module.SessionDownloadItem(
            file_name="report.pdf",
            size=42,
            download_url="https://example.com/report.pdf",
        )
    ]
    get_downloads = AsyncMock(return_value=downloaded_files)
    monkeypatch.setattr(
        environment_module,
        "_get_cloud_browser_downloads",
        get_downloads,
    )

    env = LambdaEnvironment(auth_headers={"x-api-key": "test-key"})
    env._session_id = "session-123"

    assert await env.get_downloaded_files() == downloaded_files
    get_downloads.assert_awaited_once_with(
        base_url=env._base_url,
        auth_headers={"x-api-key": "test-key"},
        session_id="session-123",
    )


@pytest.mark.asyncio
async def test_cloud_browser_environment_uses_domcontentloaded_for_login_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    env = _build_cloud_environment_with_page(page)
    context = env._playwright.chromium.connect_over_cdp.return_value.contexts[0]

    wait_for_browser_window_id = AsyncMock(return_value="browser-window-123")
    monkeypatch.setattr(
        env, "_wait_for_cloud_browser_window_id", wait_for_browser_window_id
    )

    await env._initialize_cloud_browser_window(
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
    context.add_init_script.assert_not_awaited()
    page.add_init_script.assert_awaited_once()
    assert "MutationObserver" in page.add_init_script.await_args.kwargs["script"]
    assert env.browser_window_id == "browser-window-123"
    assert env.cloud_browser_session_id == "session-123"


@pytest.mark.asyncio
async def test_cloud_browser_environment_seeds_expected_browser_window_id_before_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    env = _build_cloud_environment_with_page(page)
    events: list[str] = []

    async def add_init_script(*args, **kwargs) -> None:
        events.append("seed")

    async def goto(*args, **kwargs) -> None:
        events.append("goto")

    page.add_init_script.side_effect = add_init_script
    page.goto.side_effect = goto
    wait_for_browser_window_id = AsyncMock(return_value="backend-window-123")
    monkeypatch.setattr(
        env, "_wait_for_cloud_browser_window_id", wait_for_browser_window_id
    )

    await env._initialize_cloud_browser_window(
        cdp_websocket_url="wss://agentcore.example.test/session-123",
        session_id="session-123",
        login_url="https://app.narada.ai/chat?customToken=test-token",
        cdp_auth_headers={"Authorization": "signed-cdp"},
        expected_browser_window_id="backend-window-123",
    )

    assert events[:3] == ["seed", "seed", "goto"]
    seeded_script = page.add_init_script.await_args_list[0].kwargs["script"]
    observer_script = page.add_init_script.await_args_list[1].kwargs["script"]
    assert "MutationObserver" in observer_script
    script = seeded_script
    assert "naradaBrowserWindowId" in script
    assert "backend-window-123" in script
    assert env.browser_window_id == "backend-window-123"


@pytest.mark.asyncio
async def test_cloud_browser_environment_rejects_unexpected_seeded_browser_window_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    env = _build_cloud_environment_with_page(page)
    wait_for_browser_window_id = AsyncMock(return_value="frontend-window-123")
    monkeypatch.setattr(
        env, "_wait_for_cloud_browser_window_id", wait_for_browser_window_id
    )

    with pytest.raises(RuntimeError, match="expected 'backend-window-123'"):
        await env._initialize_cloud_browser_window(
            cdp_websocket_url="wss://agentcore.example.test/session-123",
            session_id="session-123",
            login_url="https://app.narada.ai/chat?customToken=test-token",
            cdp_auth_headers={"Authorization": "signed-cdp"},
            expected_browser_window_id="backend-window-123",
        )


@pytest.mark.asyncio
async def test_cloud_browser_environment_uses_domcontentloaded_for_retry_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    env = _build_cloud_environment_with_page(page)

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaTimeoutError("Timed out waiting for browser window ID"),
            "browser-window-123",
        ]
    )
    monkeypatch.setattr(
        env, "_wait_for_cloud_browser_window_id", wait_for_browser_window_id
    )

    await env._initialize_cloud_browser_window(
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
    assert env.browser_window_id == "browser-window-123"


@pytest.mark.asyncio
async def test_agent_run_exposes_workflow_trace_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_trace = {"step_type": "workflow", "children": []}
    env = RemoteBrowserEnvironment(
        browser_window_id="browser-window-123",
        cloud_browser_session_id="session-123",
        auth_headers={"x-api-key": "test-key"},
    )
    monkeypatch.setattr(
        env,
        "_dispatch_request",
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
                "hitlInputMetadata": None,
            }
        ),
    )

    response = await Agent(environment=env).run("return a trace")

    assert response.workflow_trace == workflow_trace
    assert response.model_dump(by_alias=True)["workflowTrace"] == workflow_trace


@pytest.mark.asyncio
async def test_agent_run_appends_critic_workflow_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_trace = {
        "workflowId": "main-workflow",
        "workflowName": "Main Workflow",
        "runtime": "gui",
        "status": "success",
        "startTs": "2026-01-01T00:00:00.000Z",
        "children": [],
    }
    critic_workflow_trace = {
        "workflowId": "critic-workflow",
        "workflowName": "Critic Workflow",
        "runtime": "gui",
        "status": "success",
        "startTs": "2026-01-01T00:00:01.000Z",
        "children": [],
    }
    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
    )
    agent = Agent(environment=env)
    monkeypatch.setattr(
        agent,
        "_dispatch_request",
        AsyncMock(
            side_effect=[
                {
                    "requestId": "request-123",
                    "status": "success",
                    "response": {
                        "text": "done",
                        "output": {"type": "text", "content": "done"},
                        "workflowTrace": workflow_trace,
                    },
                    "usage": {"actions": 0, "credits": 0},
                },
                {
                    "requestId": "critic-request-123",
                    "status": "success",
                    "response": {
                        "text": '{"narada_validation_passed":true}',
                        "output": {
                            "type": "structured",
                            "content": {"narada_validation_passed": True},
                        },
                        "structuredOutput": SimpleNamespace(
                            narada_validation_passed=True
                        ),
                        "workflowTrace": critic_workflow_trace,
                    },
                    "usage": {"actions": 0, "credits": 0},
                },
            ]
        ),
    )

    response = await agent.run("return a trace", critic={})

    assert response.critic_result is not None
    assert response.critic_result.workflow_trace == critic_workflow_trace
    assert response.workflow_trace == {
        **workflow_trace,
        "children": [{"kind": "sub_workflow", "trace": critic_workflow_trace}],
    }

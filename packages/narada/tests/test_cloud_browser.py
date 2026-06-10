import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from narada import (
    Agent,
    CloudBrowserEnvironment,
    LambdaEnvironment,
    LocalBrowserWindow,
    Narada,
    RemoteBrowserEnvironment,
)
from narada.config import BrowserConfig
from narada_core.errors import NaradaExtensionUnauthenticatedError, NaradaTimeoutError
from narada_core.models import AgentKind


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


class _FakePlaywrightContextManager:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return SimpleNamespace()

    async def __aexit__(self, *args):
        self.exited = True
        return None


def _build_cloud_environment_with_page(
    page: AsyncMock, *, browser_window_id: str = "browser-window-123"
) -> CloudBrowserEnvironment:
    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    side_panel_page = AsyncMock()
    side_panel_page.url = (
        "chrome-extension://dev-extension/sidepanel.html"
        f"?browserWindowId={browser_window_id}"
    )
    browser = SimpleNamespace(
        contexts=[SimpleNamespace(pages=[page, side_panel_page])],
        close=AsyncMock(),
    )
    env._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser))
    )
    return env


def test_cloud_browser_side_panel_url_matcher_accepts_queryless_cloud_url() -> None:
    assert CloudBrowserEnvironment._is_side_panel_page_url(
        "chrome-extension://dev-extension/sidepanel.html",
        browser_window_id="browser-window-123",
    )

    assert CloudBrowserEnvironment._is_side_panel_page_url(
        "chrome-extension://dev-extension/sidepanel.html?browserWindowId=browser-window-123",
        browser_window_id="browser-window-123",
    )

    assert not CloudBrowserEnvironment._is_side_panel_page_url(
        "chrome-extension://dev-extension/sidepanel.html?browserWindowId=other-window",
        browser_window_id="browser-window-123",
    )


def test_local_browser_window_legacy_import_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_API_KEY", "test-key")

    window = LocalBrowserWindow()

    assert isinstance(window, Agent)
    assert window.kind is AgentKind.OPERATOR
    assert Agent.OPERATOR is AgentKind.OPERATOR
    assert Agent.PRODUCTIVITY is AgentKind.PRODUCTIVITY
    assert Agent.CORE_AGENT is AgentKind.CORE_AGENT


@pytest.mark.asyncio
async def test_narada_facade_context_prepares_playwright_without_starting_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_context_manager = _FakePlaywrightContextManager()
    monkeypatch.setattr(
        environment_module,
        "async_playwright",
        lambda: fake_context_manager,
    )

    narada = Narada(auth_headers={"x-api-key": "test-key"})

    async with narada as client:
        assert client is narada
        assert fake_context_manager.entered
        assert narada._playwright is not None
        assert narada._session_id is None
        assert not narada._initialized

    assert fake_context_manager.exited
    assert narada._playwright is None


@pytest.mark.asyncio
async def test_narada_facade_accepts_legacy_cloud_initializer_config_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    narada = Narada(auth_headers={"x-api-key": "test-key"})
    side_panel_page = AsyncMock()
    side_panel_page.url = "chrome-extension://dev-extension/sidepanel.html"
    browser = SimpleNamespace(
        contexts=[SimpleNamespace(pages=[page, side_panel_page])],
        close=AsyncMock(),
    )
    narada._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser))
    )
    wait_for_browser_window_id = AsyncMock(return_value="browser-window-123")
    monkeypatch.setattr(
        narada, "_wait_for_cloud_browser_window_id", wait_for_browser_window_id
    )
    config = BrowserConfig(interactive=False)

    window = await narada._initialize_cloud_browser_window(
        config=config,
        cdp_websocket_url="wss://agentcore.example.test/session-123",
        session_id="session-123",
        login_url="https://app.narada.ai/initialize?customToken=test-token",
        cdp_auth_headers={"Authorization": "signed-cdp"},
    )

    assert window is narada
    assert narada._config is config
    assert narada.browser_window_id == "browser-window-123"
    assert narada.cloud_browser_session_id == "session-123"


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
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    observed_input_ids: list[str] = []

    async def on_input_required(active_input_request) -> None:
        observed_input_ids.append(active_input_request.input_id)

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
                "activeInputRequest": None,
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
    assert fake_session.dispatched_body["captureExecutionTrace"] is True


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
async def test_cloud_browser_environment_dev_overrides_use_dev_create_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_session = _FakeClientSession(
        {
            "cdp_websocket_url": "wss://agentcore.example.test/session-123",
            "session_id": "session-123",
            "session_name": "branch-session",
            "login_url": "https://branch.example.test/initialize?customToken=test",
            "cdp_auth_headers": {"Authorization": "signed-cdp"},
        }
    )
    monkeypatch.setattr(
        environment_module.aiohttp, "ClientSession", lambda: fake_session
    )
    monkeypatch.setattr(
        environment_module,
        "async_playwright",
        lambda: _FakePlaywrightContextManager(),
    )

    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        base_url="https://api.test/fast/v2",
        session_name="branch-session",
        session_timeout=300,
        dev_app_origin_override="https://branch.example.test",
        dev_extension_s3_bucket="narada-chrome-extension-test-builds",
        dev_extension_s3_key="proof/m5-extension.zip",
    )

    async def _initialize_window(**kwargs):
        env._session_id = kwargs["session_id"]
        env._browser_window_id = "browser-window-123"

    initialize_window = AsyncMock(side_effect=_initialize_window)
    monkeypatch.setattr(env, "_initialize_cloud_browser_window", initialize_window)

    await env.start()

    assert env.cloud_browser_session_id == "session-123"
    assert env._initialization_url == (
        "https://branch.example.test/initialize?customToken=test"
    )
    assert len(fake_session.posts) == 1
    post = fake_session.posts[0]
    assert post["url"].endswith("/cloud-browser/dev/create-cloud-browser-session")
    assert post["headers"] == {"x-api-key": "test-key"}
    assert post["json"] == {
        "require_extension": True,
        "session_name": "branch-session",
        "session_timeout": 300,
        "app_origin_override": "https://branch.example.test",
        "extension_s3_bucket": "narada-chrome-extension-test-builds",
        "extension_s3_key": "proof/m5-extension.zip",
    }
    initialize_window.assert_awaited_once_with(
        cdp_websocket_url="wss://agentcore.example.test/session-123",
        session_id="session-123",
        login_url="https://branch.example.test/initialize?customToken=test",
        cdp_auth_headers={"Authorization": "signed-cdp"},
    )


def test_cloud_browser_environment_rejects_partial_dev_overrides() -> None:
    with pytest.raises(ValueError, match="dev Cloud Browser overrides require"):
        CloudBrowserEnvironment(
            dev_app_origin_override="https://branch.example.test",
            dev_extension_s3_bucket="narada-chrome-extension-test-builds",
        )


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
    assert env.browser_window_id == "browser-window-123"
    assert env.cloud_browser_session_id == "session-123"


@pytest.mark.asyncio
async def test_cloud_browser_environment_reconnects_to_find_side_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    side_panel_page = AsyncMock()
    side_panel_page.url = (
        "chrome-extension://dev-extension/sidepanel.html"
        "?browserWindowId=browser-window-123"
    )
    second_context = SimpleNamespace(pages=[page, side_panel_page])
    side_panel_page.context = second_context
    first_browser = SimpleNamespace(
        contexts=[SimpleNamespace(pages=[page])],
        close=AsyncMock(),
    )
    second_browser = SimpleNamespace(
        contexts=[second_context],
        close=AsyncMock(),
    )
    env = CloudBrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    connect_over_cdp = AsyncMock(side_effect=[first_browser, second_browser])
    env._playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=connect_over_cdp)
    )

    wait_for_browser_window_id = AsyncMock(return_value="browser-window-123")
    monkeypatch.setattr(
        env, "_wait_for_cloud_browser_window_id", wait_for_browser_window_id
    )
    wait_for_side_panel = AsyncMock(
        side_effect=[
            NaradaTimeoutError("side panel not visible on first CDP connection"),
            side_panel_page,
        ]
    )
    monkeypatch.setattr(env, "_wait_for_cloud_side_panel_page", wait_for_side_panel)

    await env._initialize_cloud_browser_window(
        cdp_websocket_url="wss://agentcore.example.test/session-123",
        session_id="session-123",
        login_url="https://app.narada.ai/initialize?customToken=test-token",
        cdp_auth_headers={"Authorization": "signed-cdp"},
    )

    assert connect_over_cdp.await_count == 2
    first_browser.close.assert_awaited_once()
    assert wait_for_side_panel.await_count == 2
    assert env.browser_window_id == "browser-window-123"
    assert env._context is second_context


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
async def test_cloud_browser_environment_retries_extension_sign_in_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AsyncMock()
    env = _build_cloud_environment_with_page(page)

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionUnauthenticatedError(
                "Sign in to the Narada extension first"
            ),
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
                "activeInputRequest": None,
            }
        ),
    )

    response = await Agent(environment=env).run("return a trace")

    assert response.workflow_trace == workflow_trace
    assert response.model_dump(by_alias=True)["workflowTrace"] == workflow_trace

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from narada import BrowserEnvironment
from narada.config import BrowserConfig
from narada.environment import create_side_panel_url
from narada_core.actions.models import CloseWindowRequest
from narada_core.errors import (
    NaradaExtensionMissingError,
    NaradaExtensionUnauthenticatedError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)


@pytest.mark.asyncio
async def test_browser_environment_start_auto_detaches_after_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    browser = AsyncMock()
    playwright_context_manager = SimpleNamespace(__aexit__=AsyncMock())
    context = SimpleNamespace()

    async def start_playwright() -> None:
        env._playwright_context_manager = playwright_context_manager
        env._playwright = object()

    async def open_browser_window() -> None:
        env._playwright_browser = browser
        env._context = context
        env._browser_process_id = 456
        env._browser_window_id = "browser-window-123"

    monkeypatch.setattr(env, "_validate_sdk_config", AsyncMock())
    monkeypatch.setattr(env, "_start_playwright", start_playwright)
    monkeypatch.setattr(env, "_open_and_initialize_browser_window", open_browser_window)

    await env.start()

    browser.close.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env.browser_window_id == "browser-window-123"
    assert env.browser_process_id == 456
    assert env._initialized is True
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_browser_environment_detach_releases_playwright_without_closing_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    env._initialized = True
    env._browser_window_id = "browser-window-123"
    env._browser_process_id = 456
    browser = AsyncMock()
    playwright_context_manager = SimpleNamespace(__aexit__=AsyncMock())
    env._playwright_browser = browser
    env._context = SimpleNamespace()
    env._playwright_context_manager = playwright_context_manager
    env._playwright = object()
    run_extension_action = AsyncMock()
    monkeypatch.setattr(env, "_run_extension_action", run_extension_action)

    await env._detach()
    await env._detach()

    browser.close.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    run_extension_action.assert_not_awaited()
    assert env.browser_window_id == "browser-window-123"
    assert env.browser_process_id == 456
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_browser_environment_reset_agent_state_reconnects_after_detach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BrowserConfig(interactive=False)
    env = BrowserEnvironment(auth_headers={"x-api-key": "test-key"}, config=config)
    env._initialized = True
    env._browser_window_id = "browser-window-123"
    env._browser_process_id = 456

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

    connect_over_cdp.assert_awaited_once_with(config.cdp_url)
    page.reload.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env.browser_window_id == "browser-window-123"
    assert env.browser_process_id == 456
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_browser_environment_close_closes_window_before_detaching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def run_extension_action(*args: object, **kwargs: object) -> None:
        events.append("close-window")

    async def close_browser() -> None:
        events.append("close-browser")

    async def stop_playwright(*args: object) -> None:
        events.append("stop-playwright")

    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    env._initialized = True
    env._browser_window_id = "browser-window-123"
    env._playwright_browser = SimpleNamespace(close=AsyncMock(side_effect=close_browser))
    env._context = SimpleNamespace()
    env._playwright_context_manager = SimpleNamespace(
        __aexit__=AsyncMock(side_effect=stop_playwright)
    )
    env._playwright = object()
    run_extension_action_mock = AsyncMock(side_effect=run_extension_action)
    monkeypatch.setattr(env, "_run_extension_action", run_extension_action_mock)

    await env.close(timeout=7)

    run_extension_action_mock.assert_awaited_once()
    request = run_extension_action_mock.await_args.args[0]
    assert isinstance(request, CloseWindowRequest)
    assert run_extension_action_mock.await_args.kwargs == {"timeout": 7}
    assert events == ["close-window", "close-browser", "stop-playwright"]
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_browser_environment_does_not_fetch_login_token_when_already_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(return_value="browser-window-123")
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )

    page = AsyncMock()
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    fetch_browser_login_token = AsyncMock()
    monkeypatch.setattr(env, "_fetch_browser_login_token", fetch_browser_login_token)

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        BrowserConfig(interactive=False),
        "https://app.narada.ai/initialize?t=window-tag",
    )

    assert browser_window_id == "browser-window-123"
    fetch_browser_login_token.assert_not_awaited()
    page.goto.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_environment_fetches_login_token_after_unauthenticated_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionUnauthenticatedError(
                "Sign in to the Narada extension first"
            ),
            "browser-window-123",
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )

    page = AsyncMock()
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    fetch_browser_login_token = AsyncMock(return_value="custom token")
    monkeypatch.setattr(env, "_fetch_browser_login_token", fetch_browser_login_token)

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        BrowserConfig(interactive=False),
        "https://app.narada.ai/initialize?t=window-tag",
    )

    assert browser_window_id == "browser-window-123"
    fetch_browser_login_token.assert_awaited_once()
    page.goto.assert_awaited_once_with(
        "https://app.narada.ai/initialize?t=window-tag&customToken=custom+token",
        timeout=15_000,
        wait_until="domcontentloaded",
    )


@pytest.mark.asyncio
async def test_browser_window_id_wait_prefers_dom_observer() -> None:
    import narada.environment as environment_module

    page = AsyncMock()
    page.evaluate = AsyncMock(
        side_effect=[
            None,
            {"type": "browser_window_id", "browserWindowId": "browser-window-123"},
        ]
    )

    browser_window_id = await environment_module._BrowserInitializationHelper.wait_for_browser_window_id_silently(
        page,
        timeout=1_000,
    )

    assert browser_window_id == "browser-window-123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observer_result", "expected_error", "match"),
    [
        (
            {"type": "unsupported_browser"},
            NaradaUnsupportedBrowserError,
            "Unsupported browser",
        ),
        (
            {"type": "extension_missing"},
            NaradaExtensionMissingError,
            "Narada extension missing",
        ),
        (
            {"type": "extension_unauthenticated"},
            NaradaExtensionUnauthenticatedError,
            "Sign in to the Narada extension first",
        ),
        (
            {"type": "initialization_error"},
            NaradaInitializationError,
            "Initialization error",
        ),
    ],
)
async def test_browser_window_id_wait_maps_dom_observer_error_markers(
    observer_result: dict[str, str],
    expected_error: type[Exception],
    match: str,
) -> None:
    import narada.environment as environment_module

    page = AsyncMock()
    page.evaluate = AsyncMock(side_effect=[None, observer_result])

    with pytest.raises(expected_error, match=match):
        await environment_module._BrowserInitializationHelper.wait_for_browser_window_id_silently(
            page,
            timeout=1_000,
        )


@pytest.mark.asyncio
async def test_browser_window_id_wait_times_out_when_dom_observer_finds_no_marker() -> (
    None
):
    import narada.environment as environment_module

    page = AsyncMock()
    page.evaluate = AsyncMock(side_effect=[None, None])

    with pytest.raises(NaradaTimeoutError, match="Timed out"):
        await environment_module._BrowserInitializationHelper.wait_for_browser_window_id_silently(
            page,
            timeout=1_000,
        )


def test_browser_window_id_observer_script_limits_global_and_resource_leak_risk() -> (
    None
):
    import inspect

    import narada.environment as environment_module

    script = environment_module._build_browser_window_id_observer_script()
    wait_source = inspect.getsource(
        environment_module._BrowserInitializationHelper.wait_for_browser_initialization_result
    )

    assert "Symbol.for" in script
    assert "legacyGlobalKey" in script
    assert "window.top !== window" in script
    assert "function dispose()" in script
    assert "delete window[globalSymbol]" in script
    assert "delete window[legacyGlobalKey]" in script
    assert "observerState.dispose?.()" in wait_source
    assert script.index("#narada-initialization-error") < script.index(
        "#narada-browser-window-id"
    )


def test_browser_window_id_observer_script_cleans_up_in_js_runtime() -> None:
    import json
    import shutil
    import subprocess
    import textwrap

    import narada.environment as environment_module

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to execute observer lifecycle harness")

    installer_script = environment_module._build_browser_window_id_observer_script()
    harness = f"""
        const installerScript = {json.dumps(installer_script)};
        const observerKey = "narada.sdk.browserWindowIdObserver";
        const legacyKey = "__naradaBrowserWindowIdObserver";
        const markers = new Map();
        const clearedIntervals = [];
        let lastObserver = null;
        let legacyDisconnected = false;

        function assert(condition, message) {{
          if (!condition) {{
            throw new Error(message);
          }}
        }}

        const windowObject = {{}};
        windowObject.top = windowObject;
        windowObject.setInterval = () => {{
          throw new Error("observer should not poll");
        }};
        globalThis.window = windowObject;
        globalThis.clearInterval = (intervalId) => {{
          clearedIntervals.push(intervalId);
        }};

        globalThis.document = windowObject.document = {{
          documentElement: {{}},
          querySelector: (selector) => markers.get(selector) ?? null,
          addEventListener: () => {{}},
        }};

        globalThis.MutationObserver = class {{
          constructor(callback) {{
            this.callback = callback;
            this.disconnected = false;
            lastObserver = this;
          }}
          observe() {{}}
          disconnect() {{
            this.disconnected = true;
          }}
        }};

        windowObject[legacyKey] = {{
          version: 2,
          observer: {{
            disconnect: () => {{
              legacyDisconnected = true;
            }},
          }},
          intervalId: 99,
        }};

        eval(installerScript);
        const symbol = Symbol.for(observerKey);
        const state = windowObject[symbol];

        assert(windowObject[legacyKey] === undefined, "legacy string global deleted");
        assert(legacyDisconnected, "legacy observer disconnected");
        assert(clearedIntervals.includes(99), "legacy interval cleared");
        assert(state?.version === 3, "v3 state installed");
        assert(typeof state.dispose === "function", "dispose exposed");
        assert(lastObserver !== null, "mutation observer installed");

        state.dispose();
        assert(windowObject[symbol] === undefined, "symbol state deleted on dispose");
        assert(lastObserver.disconnected, "observer disconnected on dispose");

        markers.set("#narada-browser-window-id", {{ textContent: "browser-window-123" }});
        markers.set("#narada-initialization-error", {{ textContent: "" }});
        eval(installerScript);

        const precedenceState = windowObject[symbol];
        assert(
          precedenceState.result?.type === "initialization_error",
          "error marker wins over browser window ID"
        );
    """

    result = subprocess.run(
        [node, "-e", textwrap.dedent(harness)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_find_page_by_url_scans_all_browser_contexts() -> None:
    import narada.environment as environment_module

    class Page:
        def __init__(self, url: str) -> None:
            self.url = url

    class Context:
        def __init__(self, pages: list[Page]) -> None:
            self.pages = pages

    class Browser:
        contexts = [
            Context([Page("https://app.narada.ai/initialize?t=tag")]),
            Context(
                [
                    Page(
                        "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
                        "sidepanel.html?browserWindowId=browser-window-123"
                    )
                ]
            ),
        ]

    side_panel_url = (
        "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
        "sidepanel.html?browserWindowId=browser-window-123"
    )
    page = environment_module._find_page_by_url(
        Browser(),
        side_panel_url,
    )

    assert page is Browser.contexts[1].pages[0]


@pytest.mark.asyncio
async def test_fix_download_behavior_uses_browser_level_cdp_without_page() -> None:
    class BrowserCdpSession:
        def __init__(self) -> None:
            self.commands: list[tuple[str, dict[str, str]]] = []
            self.detached = False

        async def send(self, method: str, params: dict[str, str]) -> dict[str, str]:
            self.commands.append((method, params))
            return {}

        async def detach(self) -> None:
            self.detached = True

    class Browser:
        def __init__(self) -> None:
            self.cdp_session = BrowserCdpSession()

        async def new_browser_cdp_session(self) -> BrowserCdpSession:
            return self.cdp_session

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    context = Context()
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    await env._fix_download_behavior(context, None)  # type: ignore[arg-type]

    assert context.browser.cdp_session.commands == [
        ("Browser.setDownloadBehavior", {"behavior": "default"})
    ]
    assert context.browser.cdp_session.detached


@pytest.mark.asyncio
async def test_fix_download_behavior_falls_back_to_page_cdp() -> None:
    class BrowserCdpSession:
        def __init__(self) -> None:
            self.detached = False

        async def send(self, method: str, params: dict[str, str]) -> dict[str, str]:
            raise RuntimeError("browser-level CDP unavailable")

        async def detach(self) -> None:
            self.detached = True

    class PageCdpSession:
        def __init__(self) -> None:
            self.commands: list[tuple[str, dict[str, str]]] = []
            self.detached = False

        async def send(self, method: str, params: dict[str, str]) -> dict[str, str]:
            self.commands.append((method, params))
            return {}

        async def detach(self) -> None:
            self.detached = True

    class Browser:
        def __init__(self) -> None:
            self.cdp_session = BrowserCdpSession()

        async def new_browser_cdp_session(self) -> BrowserCdpSession:
            return self.cdp_session

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    class PageContext:
        def __init__(self) -> None:
            self.cdp_session = PageCdpSession()

        async def new_cdp_session(self, page: object) -> PageCdpSession:
            return self.cdp_session

    class Page:
        def __init__(self) -> None:
            self.context = PageContext()

    context = Context()
    page = Page()
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    await env._fix_download_behavior(context, page)  # type: ignore[arg-type]

    assert context.browser.cdp_session.detached
    assert page.context.cdp_session.commands == [
        ("Page.setDownloadBehavior", {"behavior": "default"})
    ]
    assert page.context.cdp_session.detached


@pytest.mark.asyncio
async def test_fix_download_behavior_detaches_page_cdp_after_failure() -> None:
    class BrowserCdpSession:
        def __init__(self) -> None:
            self.detached = False

        async def send(self, method: str, params: dict[str, str]) -> dict[str, str]:
            raise RuntimeError("browser-level CDP unavailable")

        async def detach(self) -> None:
            self.detached = True

    class PageCdpSession:
        def __init__(self) -> None:
            self.detached = False

        async def send(self, method: str, params: dict[str, str]) -> dict[str, str]:
            raise RuntimeError("page-level CDP failed")

        async def detach(self) -> None:
            self.detached = True

    class Browser:
        def __init__(self) -> None:
            self.cdp_session = BrowserCdpSession()

        async def new_browser_cdp_session(self) -> BrowserCdpSession:
            return self.cdp_session

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    class PageContext:
        def __init__(self) -> None:
            self.cdp_session = PageCdpSession()

        async def new_cdp_session(self, page: object) -> PageCdpSession:
            return self.cdp_session

    class Page:
        def __init__(self) -> None:
            self.context = PageContext()

    context = Context()
    page = Page()
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    with pytest.raises(RuntimeError, match="page-level CDP failed"):
        await env._fix_download_behavior(context, page)  # type: ignore[arg-type]

    assert context.browser.cdp_session.detached
    assert page.context.cdp_session.detached


@pytest.mark.asyncio
async def test_has_cdp_target_url_accepts_target_without_page() -> None:
    import narada.environment as environment_module

    class CdpSession:
        async def send(self, method: str) -> dict[str, list[dict[str, str]]]:
            assert method == "Target.getTargets"
            return {
                "targetInfos": [
                    {
                        "url": "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
                        "sidepanel.html?browserWindowId=browser-window-123"
                    }
                ]
            }

        async def detach(self) -> None:
            pass

    class Browser:
        async def new_browser_cdp_session(self) -> CdpSession:
            return CdpSession()

    side_panel_url = (
        "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
        "sidepanel.html?browserWindowId=browser-window-123"
    )

    assert await environment_module._has_cdp_target_url(
        Browser(),
        side_panel_url,
    )


@pytest.mark.asyncio
async def test_has_cdp_target_url_rejects_missing_target() -> None:
    import narada.environment as environment_module

    class CdpSession:
        async def send(self, method: str) -> dict[str, list[dict[str, str]]]:
            assert method == "Target.getTargets"
            return {"targetInfos": [{"url": "https://app.narada.ai/initialize?t=tag"}]}

        async def detach(self) -> None:
            pass

    class Browser:
        async def new_browser_cdp_session(self) -> CdpSession:
            return CdpSession()

    side_panel_url = (
        "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
        "sidepanel.html?browserWindowId=browser-window-123"
    )

    assert not await environment_module._has_cdp_target_url(
        Browser(),
        side_panel_url,
    )

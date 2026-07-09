from unittest.mock import AsyncMock

import pytest
from narada import BrowserEnvironment
from narada.config import BrowserConfig
from narada_core.errors import (
    NaradaExtensionMissingError,
    NaradaExtensionUnauthenticatedError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)


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
async def test_open_initialization_stores_target_only_match_for_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    import narada.environment as environment_module

    class BrowserCdpSession:
        def __init__(self) -> None:
            self.commands: list[tuple[str, dict[str, str]]] = []
            self.detached = False

        async def send(self, method: str, params: dict[str, str]) -> dict[str, str]:
            self.commands.append((method, params))
            if method == "Target.attachToTarget":
                return {"sessionId": "target-session-123"}
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
            self.pages: list[object] = []

    context = Context()
    side_panel_match = environment_module._SidePanelMatch(
        page=None,
        target_id="target-123",
        browser_context_id="browser-context-123",
    )
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    env._playwright = object()  # type: ignore[assignment]
    launch_browser = AsyncMock(
        return_value=environment_module._LaunchBrowserResult(
            browser_process_id=123,
            browser_window_id="browser-window-123",
            browser_context=context,
            side_panel_match=side_panel_match,
        )
    )
    fix_download_behavior = AsyncMock()
    monkeypatch.setattr(env, "_launch_browser", launch_browser)
    monkeypatch.setattr(env, "_fix_download_behavior", fix_download_behavior)

    await env._open_and_initialize_browser_window()

    assert env._side_panel_match is side_panel_match
    fix_download_behavior.assert_awaited_once_with(context, side_panel_match)

    env._initialized = True
    await env.reset_agent_state()

    commands = context.browser.cdp_session.commands
    assert commands[0] == ("Target.attachToTarget", {"targetId": "target-123"})
    assert commands[1][0] == "Target.sendMessageToTarget"
    assert commands[1][1]["sessionId"] == "target-session-123"
    assert json.loads(commands[1][1]["message"]) == {
        "id": 1,
        "method": "Page.reload",
    }
    assert commands[2] == (
        "Target.detachFromTarget",
        {"sessionId": "target-session-123"},
    )
    assert context.browser.cdp_session.detached


@pytest.mark.asyncio
async def test_fix_download_behavior_uses_browser_context_for_target_only_match() -> (
    None
):
    import narada.environment as environment_module

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
    side_panel_match = environment_module._SidePanelMatch(
        page=None,
        target_id="target-123",
        browser_context_id="browser-context-123",
    )
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    await env._fix_download_behavior(context, side_panel_match)  # type: ignore[arg-type]

    assert context.browser.cdp_session.commands == [
        (
            "Browser.setDownloadBehavior",
            {"behavior": "default", "browserContextId": "browser-context-123"},
        )
    ]
    assert context.browser.cdp_session.detached


@pytest.mark.asyncio
async def test_fix_download_behavior_uses_page_cdp_for_page_match() -> None:
    import narada.environment as environment_module

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
            self.new_browser_cdp_session_called = False

        async def new_browser_cdp_session(self) -> object:
            self.new_browser_cdp_session_called = True
            raise AssertionError("browser-level CDP should not be used")

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
    side_panel_match = environment_module._SidePanelMatch(
        page=page,  # type: ignore[arg-type]
        target_id=None,
        browser_context_id=None,
    )
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    await env._fix_download_behavior(context, side_panel_match)  # type: ignore[arg-type]

    assert not context.browser.new_browser_cdp_session_called
    assert page.context.cdp_session.commands == [
        ("Page.setDownloadBehavior", {"behavior": "default"})
    ]
    assert page.context.cdp_session.detached


@pytest.mark.asyncio
async def test_fix_download_behavior_detaches_browser_cdp_after_failure() -> None:
    import narada.environment as environment_module

    class BrowserCdpSession:
        def __init__(self) -> None:
            self.detached = False

        async def send(self, method: str, params: dict[str, str]) -> dict[str, str]:
            raise RuntimeError("browser-level CDP failed")

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
    side_panel_match = environment_module._SidePanelMatch(
        page=None,
        target_id="target-123",
        browser_context_id="browser-context-123",
    )
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    with pytest.raises(NaradaInitializationError, match="CDP target"):
        await env._fix_download_behavior(context, side_panel_match)  # type: ignore[arg-type]

    assert context.browser.cdp_session.detached


@pytest.mark.asyncio
async def test_fix_download_behavior_detaches_page_cdp_after_failure() -> None:
    import narada.environment as environment_module

    class Browser:
        def __init__(self) -> None:
            self.new_browser_cdp_session_called = False

        async def new_browser_cdp_session(self) -> object:
            self.new_browser_cdp_session_called = True
            raise AssertionError("browser-level CDP should not be used")

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    class PageCdpSession:
        def __init__(self) -> None:
            self.detached = False

        async def send(self, method: str, params: dict[str, str]) -> dict[str, str]:
            raise RuntimeError("page-level CDP failed")

        async def detach(self) -> None:
            self.detached = True

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
    side_panel_match = environment_module._SidePanelMatch(
        page=page,  # type: ignore[arg-type]
        target_id=None,
        browser_context_id=None,
    )
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    with pytest.raises(RuntimeError, match="page-level CDP failed"):
        await env._fix_download_behavior(context, side_panel_match)  # type: ignore[arg-type]

    assert not context.browser.new_browser_cdp_session_called
    assert page.context.cdp_session.detached


@pytest.mark.asyncio
async def test_find_side_panel_match_accepts_target_without_page() -> None:
    import narada.environment as environment_module

    class CdpSession:
        async def send(self, method: str) -> dict[str, list[dict[str, str]]]:
            assert method == "Target.getTargets"
            return {
                "targetInfos": [
                    {
                        "targetId": "target-123",
                        "browserContextId": "browser-context-123",
                        "url": "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
                        "sidepanel.html?browserWindowId=browser-window-123",
                    }
                ]
            }

        async def detach(self) -> None:
            pass

    class Browser:
        contexts: list[object] = []

        async def new_browser_cdp_session(self) -> CdpSession:
            return CdpSession()

    side_panel_url = (
        "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
        "sidepanel.html?browserWindowId=browser-window-123"
    )

    side_panel_match = await environment_module._find_side_panel_match(
        Browser(),
        side_panel_url,
    )

    assert side_panel_match == environment_module._SidePanelMatch(
        page=None,
        target_id="target-123",
        browser_context_id="browser-context-123",
    )


@pytest.mark.asyncio
async def test_find_side_panel_match_rejects_missing_target() -> None:
    import narada.environment as environment_module

    class CdpSession:
        async def send(self, method: str) -> dict[str, list[dict[str, str]]]:
            assert method == "Target.getTargets"
            return {"targetInfos": [{"url": "https://app.narada.ai/initialize?t=tag"}]}

        async def detach(self) -> None:
            pass

    class Browser:
        contexts: list[object] = []

        async def new_browser_cdp_session(self) -> CdpSession:
            return CdpSession()

    side_panel_url = (
        "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
        "sidepanel.html?browserWindowId=browser-window-123"
    )

    assert (
        await environment_module._find_side_panel_match(
            Browser(),
            side_panel_url,
        )
        is None
    )


@pytest.mark.asyncio
async def test_launch_browser_limits_browser_window_id_timeout_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    class BrowserProcess:
        pid = 123

    class Page:
        def __init__(self, state: dict[str, str]) -> None:
            self._state = state

        @property
        def url(self) -> str:
            return self._state["initialization_url"]

        async def bring_to_front(self) -> None:
            pass

        async def goto(self, url: str, *, timeout: int, wait_until: str) -> None:
            self._state["initialization_url"] = url

    class Context:
        def __init__(self, state: dict[str, str]) -> None:
            self.pages = [Page(state)]

    class Browser:
        def __init__(self, state: dict[str, str]) -> None:
            self.contexts = [Context(state)]
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class Chromium:
        def __init__(self, state: dict[str, str]) -> None:
            self._state = state
            self.connect_count = 0

        async def connect_over_cdp(self, cdp_url: str) -> Browser:
            self.connect_count += 1
            return Browser(self._state)

    class Playwright:
        def __init__(self, state: dict[str, str]) -> None:
            self.chromium = Chromium(state)

    state = {"initialization_url": ""}

    async def create_subprocess_exec(
        executable_path: str,
        *browser_args: str,
        **kwargs: object,
    ) -> BrowserProcess:
        state["initialization_url"] = browser_args[-1]
        return BrowserProcess()

    monkeypatch.setattr(
        environment_module.asyncio,
        "create_subprocess_exec",
        create_subprocess_exec,
    )
    monkeypatch.setattr(environment_module.asyncio, "sleep", AsyncMock())

    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    wait_for_browser_window_id = AsyncMock(
        side_effect=NaradaTimeoutError("Timed out waiting for browser window ID")
    )
    monkeypatch.setattr(
        env,
        "_wait_for_browser_window_id_with_lazy_login",
        wait_for_browser_window_id,
    )
    playwright = Playwright(state)

    with pytest.raises(NaradaTimeoutError):
        await env._launch_browser(playwright, env._config)  # type: ignore[arg-type]

    assert wait_for_browser_window_id.await_count == 2
    assert playwright.chromium.connect_count == 2

from unittest.mock import AsyncMock, Mock

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
async def test_browser_environment_retries_missing_extension_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionMissingError("Narada extension missing"),
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    read_initialization_result = AsyncMock(
        side_effect=[
            None,
            None,
            {"type": "browser_window_id", "browserWindowId": "browser-window-123"},
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "read_browser_initialization_result_ignoring_extension_missing",
        read_initialization_result,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    initialization_url = "https://app.narada.ai/initialize?t=window-tag"
    page = AsyncMock()
    page.url = initialization_url
    console_input = Mock()
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=True),
    )
    monkeypatch.setattr(env._console, "input", console_input)
    extension_target_active = AsyncMock(return_value=False)
    monkeypatch.setattr(
        env, "_has_extension_cdp_target_for_browser_page", extension_target_active
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_installed_in_local_profile",
        Mock(return_value=False),
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_force_listed_in_chrome_policy",
        Mock(return_value=False),
    )

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        BrowserConfig(interactive=True),
        initialization_url,
    )

    assert browser_window_id == "browser-window-123"
    assert sleep.await_count == 3
    assert read_initialization_result.await_count == 3
    assert extension_target_active.await_count == 2
    page.reload.assert_not_awaited()
    console_input.assert_not_called()


@pytest.mark.asyncio
async def test_browser_environment_reloads_once_after_extension_target_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionMissingError("Narada extension missing"),
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    read_initialization_result = AsyncMock(
        side_effect=[
            None,
            None,
            {"type": "browser_window_id", "browserWindowId": "browser-window-123"},
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "read_browser_initialization_result_ignoring_extension_missing",
        read_initialization_result,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    initialization_url = "https://app.narada.ai/initialize?t=window-tag"
    page = AsyncMock()
    page.url = initialization_url
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    extension_target_active = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(
        env, "_has_extension_cdp_target_for_browser_page", extension_target_active
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_installed_in_local_profile",
        Mock(return_value=False),
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_force_listed_in_chrome_policy",
        Mock(return_value=False),
    )

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        BrowserConfig(interactive=False),
        initialization_url,
    )

    assert browser_window_id == "browser-window-123"
    assert sleep.await_count == 2
    page.reload.assert_awaited_once_with(
        timeout=15_000,
        wait_until="domcontentloaded",
    )
    page.bring_to_front.assert_awaited_once()
    wait_for_browser_window_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_environment_reloads_once_on_final_profile_install_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionMissingError("Narada extension missing"),
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    read_initialization_result = AsyncMock(
        side_effect=[
            *[None] * environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS,
            {"type": "browser_window_id", "browserWindowId": "browser-window-123"},
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "read_browser_initialization_result_ignoring_extension_missing",
        read_initialization_result,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)
    local_profile_check = Mock(
        side_effect=[
            *[False] * (environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS - 1),
            True,
        ]
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_installed_in_local_profile",
        local_profile_check,
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_force_listed_in_chrome_policy",
        Mock(return_value=False),
    )

    initialization_url = "https://app.narada.ai/initialize?t=window-tag"
    page = AsyncMock()
    page.url = initialization_url
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    extension_target_active = AsyncMock(return_value=False)
    monkeypatch.setattr(
        env, "_has_extension_cdp_target_for_browser_page", extension_target_active
    )

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        BrowserConfig(interactive=False),
        initialization_url,
    )

    assert browser_window_id == "browser-window-123"
    assert sleep.await_count == environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS
    assert local_profile_check.call_count == environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS
    page.reload.assert_awaited_once_with(
        timeout=15_000,
        wait_until="domcontentloaded",
    )
    page.bring_to_front.assert_awaited_once()
    wait_for_browser_window_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_environment_reloads_once_on_final_policy_install_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionMissingError("Narada extension missing"),
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    read_initialization_result = AsyncMock(
        side_effect=[
            *[None] * environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS,
            {"type": "browser_window_id", "browserWindowId": "browser-window-123"},
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "read_browser_initialization_result_ignoring_extension_missing",
        read_initialization_result,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        environment_module,
        "_is_extension_installed_in_local_profile",
        Mock(return_value=False),
    )
    policy_check = Mock(
        side_effect=[
            *[False] * (environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS - 1),
            True,
        ]
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_force_listed_in_chrome_policy",
        policy_check,
    )

    initialization_url = "https://app.narada.ai/initialize?t=window-tag"
    page = AsyncMock()
    page.url = initialization_url
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    extension_target_active = AsyncMock(return_value=False)
    monkeypatch.setattr(
        env, "_has_extension_cdp_target_for_browser_page", extension_target_active
    )

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        BrowserConfig(interactive=False),
        initialization_url,
    )

    assert browser_window_id == "browser-window-123"
    assert sleep.await_count == environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS
    assert policy_check.call_count == environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS
    page.reload.assert_awaited_once_with(
        timeout=15_000,
        wait_until="domcontentloaded",
    )
    page.bring_to_front.assert_awaited_once()
    wait_for_browser_window_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_environment_retries_missing_extension_before_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=NaradaExtensionMissingError("Narada extension missing")
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    read_initialization_result = AsyncMock(return_value=None)
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "read_browser_initialization_result_ignoring_extension_missing",
        read_initialization_result,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    initialization_url = "https://app.narada.ai/initialize?t=window-tag"
    page = AsyncMock()
    page.url = initialization_url
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    extension_target_active = AsyncMock(return_value=False)
    monkeypatch.setattr(
        env, "_has_extension_cdp_target_for_browser_page", extension_target_active
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_installed_in_local_profile",
        Mock(return_value=False),
    )
    monkeypatch.setattr(
        environment_module,
        "_is_extension_force_listed_in_chrome_policy",
        Mock(return_value=False),
    )

    with pytest.raises(NaradaExtensionMissingError, match="Narada extension missing"):
        await env._wait_for_browser_window_id_with_lazy_login(
            page,
            BrowserConfig(interactive=False),
            initialization_url,
        )

    wait_for_browser_window_id.assert_awaited_once()
    assert sleep.await_count == environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS
    assert (
        read_initialization_result.await_count
        == environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS
    )
    assert extension_target_active.await_count == environment_module._EXTENSION_MISSING_RETRY_ATTEMPTS
    page.reload.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_environment_does_not_reload_after_user_leaves_initialization_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=NaradaExtensionMissingError("Narada extension missing")
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    read_initialization_result = AsyncMock()
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "read_browser_initialization_result_ignoring_extension_missing",
        read_initialization_result,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    initialization_url = "https://app.narada.ai/initialize?t=window-tag"
    page = AsyncMock()
    page.url = "https://chromewebstore.google.com/detail/narada/example"
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    extension_target_active = AsyncMock()
    monkeypatch.setattr(
        env, "_has_extension_cdp_target_for_browser_page", extension_target_active
    )
    local_profile_check = Mock()
    monkeypatch.setattr(
        environment_module,
        "_is_extension_installed_in_local_profile",
        local_profile_check,
    )
    policy_check = Mock()
    monkeypatch.setattr(
        environment_module,
        "_is_extension_force_listed_in_chrome_policy",
        policy_check,
    )

    with pytest.raises(NaradaExtensionMissingError, match="Narada extension missing"):
        await env._wait_for_browser_window_id_with_lazy_login(
            page,
            BrowserConfig(interactive=False),
            initialization_url,
        )

    sleep.assert_awaited_once_with(
        environment_module._EXTENSION_MISSING_RETRY_DELAY_SECONDS
    )
    read_initialization_result.assert_not_awaited()
    extension_target_active.assert_not_awaited()
    local_profile_check.assert_not_called()
    policy_check.assert_not_called()
    page.reload.assert_not_awaited()
    wait_for_browser_window_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_environment_uses_lazy_login_after_extension_retry_auth_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionMissingError("Narada extension missing"),
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
    read_initialization_result = AsyncMock(
        return_value={"type": "extension_unauthenticated"}
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "read_browser_initialization_result_ignoring_extension_missing",
        read_initialization_result,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    initialization_url = "https://app.narada.ai/initialize?t=window-tag"
    page = AsyncMock()
    page.url = initialization_url
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    fetch_browser_login_token = AsyncMock(return_value="custom token")
    monkeypatch.setattr(env, "_fetch_browser_login_token", fetch_browser_login_token)

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        BrowserConfig(interactive=False),
        initialization_url,
    )

    assert browser_window_id == "browser-window-123"
    page.reload.assert_not_awaited()
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

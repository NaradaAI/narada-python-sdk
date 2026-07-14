import asyncio
import json
import subprocess
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
async def test_browser_environment_start_detaches_after_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    browser = AsyncMock()
    playwright_context_manager = SimpleNamespace(__aexit__=AsyncMock())
    initialization_error = RuntimeError("initialization failed")

    async def start_playwright() -> None:
        env._playwright_context_manager = playwright_context_manager
        env._playwright = object()

    async def open_browser_window() -> None:
        env._playwright_browser = browser
        env._context = SimpleNamespace()
        raise initialization_error

    monkeypatch.setattr(env, "_validate_sdk_config", AsyncMock())
    monkeypatch.setattr(env, "_start_playwright", start_playwright)
    monkeypatch.setattr(env, "_open_and_initialize_browser_window", open_browser_window)

    with pytest.raises(RuntimeError, match="initialization failed"):
        await env.start()

    browser.close.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env._initialized is False
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_browser_environment_start_cleans_up_when_playwright_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    startup_error = RuntimeError("Playwright startup failed")
    playwright_context_manager = SimpleNamespace(
        __aenter__=AsyncMock(side_effect=startup_error),
        __aexit__=AsyncMock(),
    )
    monkeypatch.setattr(env, "_validate_sdk_config", AsyncMock())
    monkeypatch.setattr(
        environment_module,
        "async_playwright",
        lambda: playwright_context_manager,
    )

    with pytest.raises(RuntimeError, match="Playwright startup failed"):
        await env.start()

    playwright_context_manager.__aenter__.assert_awaited_once()
    playwright_context_manager.__aexit__.assert_awaited_once_with(None, None, None)
    assert env._initialized is False
    assert env._playwright_browser is None
    assert env._context is None
    assert env._playwright is None
    assert env._playwright_context_manager is None


@pytest.mark.asyncio
async def test_browser_environment_close_waits_for_start_to_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    detach_started = asyncio.Event()
    finish_detach = asyncio.Event()
    detach_calls = 0

    async def open_browser_window() -> None:
        env._browser_process_id = 456
        env._browser_window_id = "browser-window-123"

    async def detach() -> None:
        nonlocal detach_calls
        detach_calls += 1
        if detach_calls == 1:
            detach_started.set()
            await finish_detach.wait()

    run_extension_action = AsyncMock()
    monkeypatch.setattr(env, "_validate_sdk_config", AsyncMock())
    monkeypatch.setattr(env, "_start_playwright", AsyncMock())
    monkeypatch.setattr(env, "_open_and_initialize_browser_window", open_browser_window)
    monkeypatch.setattr(env, "_detach", detach)
    monkeypatch.setattr(env, "_run_extension_action", run_extension_action)

    start_task = asyncio.create_task(env.start())
    await detach_started.wait()
    close_task = asyncio.create_task(env.close())
    await asyncio.sleep(0)

    assert not close_task.done()
    run_extension_action.assert_not_awaited()

    finish_detach.set()
    await start_task
    await close_task

    request = run_extension_action.await_args.args[0]
    assert isinstance(request, CloseWindowRequest)
    assert env._initialized is True
    assert detach_calls == 2


@pytest.mark.asyncio
async def test_browser_environment_cancelled_post_start_cleanup_does_not_reinitialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    detach_started = asyncio.Event()
    detach_calls = 0

    async def open_browser_window() -> None:
        env._browser_process_id = 456
        env._browser_window_id = "browser-window-123"

    async def detach() -> None:
        nonlocal detach_calls
        detach_calls += 1
        if detach_calls == 1:
            detach_started.set()
            await asyncio.Future()

    open_browser_window_mock = AsyncMock(side_effect=open_browser_window)
    run_extension_action = AsyncMock()
    monkeypatch.setattr(env, "_validate_sdk_config", AsyncMock())
    monkeypatch.setattr(env, "_start_playwright", AsyncMock())
    monkeypatch.setattr(
        env, "_open_and_initialize_browser_window", open_browser_window_mock
    )
    monkeypatch.setattr(env, "_detach", detach)
    monkeypatch.setattr(env, "_run_extension_action", run_extension_action)

    start_task = asyncio.create_task(env.start())
    await detach_started.wait()
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    assert env._initialized is True
    await env.start()
    open_browser_window_mock.assert_awaited_once()

    await env.close()
    request = run_extension_action.await_args.args[0]
    assert isinstance(request, CloseWindowRequest)
    assert detach_calls == 2


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
    context = SimpleNamespace(pages=[page])
    browser = SimpleNamespace(
        contexts=[context],
        close=AsyncMock(),
    )
    context.browser = browser
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
    env._playwright_browser = SimpleNamespace(
        close=AsyncMock(side_effect=close_browser)
    )
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


@pytest.mark.parametrize(
    "registry_value",
    [
        "  BHIOAIDLGGJDKHEAAJAKOMIFBLPJMOKN  ",
        (
            "bhioaidlggjdkheaajakomifblpjmokn;"
            "https://clients2.google.com/service/update2/crx"
        ),
    ],
)
def test_is_win_extension_autoload_used_matches_force_install_value(
    monkeypatch: pytest.MonkeyPatch,
    registry_value: str,
) -> None:
    import narada.environment as environment_module

    registry_key = object()
    registry_key_context = MagicMock()
    registry_key_context.__enter__.return_value = registry_key
    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        REG_SZ=1,
        OpenKey=MagicMock(return_value=registry_key_context),
        QueryInfoKey=MagicMock(return_value=(0, 1, 0)),
        EnumValue=MagicMock(return_value=("1", registry_value, 1)),
    )
    monkeypatch.setattr(environment_module.sys, "platform", "win32")
    monkeypatch.setattr(environment_module, "winreg", fake_winreg)

    assert environment_module.is_win_extension_autoload_used(
        "bhioaidlggjdkheaajakomifblpjmokn"
    )
    fake_winreg.OpenKey.assert_called_once_with(
        fake_winreg.HKEY_LOCAL_MACHINE,
        r"Software\Policies\Google\Chrome\ExtensionInstallForcelist",
    )
    fake_winreg.QueryInfoKey.assert_called_once_with(registry_key)
    fake_winreg.EnumValue.assert_called_once_with(registry_key, 0)


def test_is_win_extension_autoload_used_ignores_unrelated_and_malformed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    registry_key = object()
    registry_key_context = MagicMock()
    registry_key_context.__enter__.return_value = registry_key
    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        REG_SZ=1,
        OpenKey=MagicMock(return_value=registry_key_context),
        QueryInfoKey=MagicMock(return_value=(0, 3, 0)),
        EnumValue=MagicMock(
            side_effect=[
                ("1", "unrelatedextensionid", 1),
                ("2", 123, 1),
                ("3", "bhioaidlggjdkheaajakomifblpjmokn", 2),
            ]
        ),
    )
    monkeypatch.setattr(environment_module.sys, "platform", "win32")
    monkeypatch.setattr(environment_module, "winreg", fake_winreg)

    assert not environment_module.is_win_extension_autoload_used(
        "bhioaidlggjdkheaajakomifblpjmokn"
    )
    assert fake_winreg.EnumValue.call_count == 3


@pytest.mark.parametrize("registry_error", [FileNotFoundError(), PermissionError()])
def test_is_win_extension_autoload_used_returns_false_for_unreadable_registry(
    monkeypatch: pytest.MonkeyPatch,
    registry_error: OSError,
) -> None:
    import narada.environment as environment_module

    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        REG_SZ=1,
        OpenKey=MagicMock(side_effect=registry_error),
    )
    monkeypatch.setattr(environment_module.sys, "platform", "win32")
    monkeypatch.setattr(environment_module, "winreg", fake_winreg)

    assert not environment_module.is_win_extension_autoload_used(
        "bhioaidlggjdkheaajakomifblpjmokn"
    )


def test_is_win_extension_autoload_used_returns_false_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    fake_winreg = SimpleNamespace(OpenKey=MagicMock())
    monkeypatch.setattr(environment_module.sys, "platform", "linux")
    monkeypatch.setattr(environment_module, "winreg", fake_winreg)

    assert not environment_module.is_win_extension_autoload_used(
        "bhioaidlggjdkheaajakomifblpjmokn"
    )
    fake_winreg.OpenKey.assert_not_called()


@pytest.mark.asyncio
async def test_browser_environment_retries_missing_extension_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionMissingError("Narada extension missing"),
            NaradaExtensionMissingError("Narada extension missing"),
            NaradaExtensionMissingError("Narada extension missing"),
            "browser-window-123",
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    monkeypatch.setattr(environment_module.sys, "platform", "win32")
    is_extension_autoloaded = MagicMock(return_value=True)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        is_extension_autoloaded,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    page = AsyncMock()
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=True),
    )
    input_calls: list[str] = []
    monkeypatch.setattr(env._console, "input", input_calls.append)

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        env._config,
        "https://app.narada.ai/initialize?t=window-tag",
    )

    assert browser_window_id == "browser-window-123"
    assert wait_for_browser_window_id.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [3, 0.1] * 3
    assert page.bring_to_front.await_count == 3
    assert page.reload.await_count == 3
    assert input_calls == []
    is_extension_autoloaded.assert_called_once_with(env._config.extension_id)


@pytest.mark.asyncio
async def test_browser_environment_prompts_after_windows_extension_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            *[
                NaradaExtensionMissingError("Narada extension missing")
                for _ in range(5)
            ],
            "browser-window-123",
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    monkeypatch.setattr(environment_module.sys, "platform", "win32")
    is_extension_autoloaded = MagicMock(return_value=True)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        is_extension_autoloaded,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    page = AsyncMock()
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=True),
    )
    input_call_state: list[tuple[int, int]] = []

    def record_input(_prompt: str) -> None:
        input_call_state.append((sleep.await_count, page.reload.await_count))

    monkeypatch.setattr(env._console, "input", record_input)

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        env._config,
        "https://app.narada.ai/initialize?t=window-tag",
    )

    assert browser_window_id == "browser-window-123"
    assert wait_for_browser_window_id.await_count == 6
    assert input_call_state == [(6, 3), (7, 4)]
    assert [call.args[0] for call in sleep.await_args_list] == [3, 0.1] * 3 + [
        0.1,
        0.1,
    ]
    assert page.bring_to_front.await_count == 5
    assert page.reload.await_count == 5
    is_extension_autoloaded.assert_called_once_with(env._config.extension_id)


@pytest.mark.asyncio
async def test_browser_environment_prompts_immediately_when_extension_is_not_autoloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    wait_for_browser_window_id = AsyncMock(
        side_effect=[
            NaradaExtensionMissingError("Narada extension missing"),
            "browser-window-123",
        ]
    )
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        wait_for_browser_window_id,
    )
    monkeypatch.setattr(environment_module.sys, "platform", "win32")
    is_extension_autoloaded = MagicMock(return_value=False)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        is_extension_autoloaded,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    page = AsyncMock()
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=True),
    )
    input_calls: list[str] = []
    monkeypatch.setattr(env._console, "input", input_calls.append)

    browser_window_id = await env._wait_for_browser_window_id_with_lazy_login(
        page,
        env._config,
        "https://app.narada.ai/initialize?t=window-tag",
    )

    assert browser_window_id == "browser-window-123"
    assert len(input_calls) == 1
    sleep.assert_awaited_once_with(0.1)
    page.bring_to_front.assert_awaited_once()
    page.reload.assert_awaited_once()
    is_extension_autoloaded.assert_called_once_with(env._config.extension_id)


@pytest.mark.asyncio
async def test_browser_environment_does_not_retry_missing_extension_when_noninteractive(
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
    monkeypatch.setattr(environment_module.sys, "platform", "win32")
    is_extension_autoloaded = MagicMock(return_value=False)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        is_extension_autoloaded,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    page = AsyncMock()
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    input_calls: list[str] = []
    monkeypatch.setattr(env._console, "input", input_calls.append)

    with pytest.raises(NaradaExtensionMissingError, match="Narada extension missing"):
        await env._wait_for_browser_window_id_with_lazy_login(
            page,
            env._config,
            "https://app.narada.ai/initialize?t=window-tag",
        )

    wait_for_browser_window_id.assert_awaited_once()
    sleep.assert_not_awaited()
    page.bring_to_front.assert_not_awaited()
    page.reload.assert_not_awaited()
    assert input_calls == []
    is_extension_autoloaded.assert_called_once_with(env._config.extension_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("restart_on_autoload_failure", [False, True])
async def test_browser_environment_exhausts_autoload_retries_when_noninteractive(
    monkeypatch: pytest.MonkeyPatch,
    restart_on_autoload_failure: bool,
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
    is_extension_autoloaded = MagicMock(return_value=True)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        is_extension_autoloaded,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(environment_module.asyncio, "sleep", sleep)

    page = AsyncMock()
    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )

    expected_error = (
        environment_module._BrowserAutoloadRestartRequired
        if restart_on_autoload_failure
        else NaradaExtensionMissingError
    )
    with pytest.raises(expected_error):
        await env._wait_for_browser_window_id_with_lazy_login(
            page,
            env._config,
            "https://app.narada.ai/initialize?t=window-tag",
            restart_on_autoload_failure=restart_on_autoload_failure,
        )

    assert wait_for_browser_window_id.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [3, 0.1] * 3
    assert page.bring_to_front.await_count == 3
    assert page.reload.await_count == 3
    is_extension_autoloaded.assert_called_once_with(env._config.extension_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("restart_on_autoload_failure", [False, True])
async def test_browser_environment_handles_closed_initialization_page(
    monkeypatch: pytest.MonkeyPatch,
    restart_on_autoload_failure: bool,
) -> None:
    import narada.environment as environment_module

    playwright_error = environment_module.PlaywrightError("page closed")
    monkeypatch.setattr(
        environment_module._BrowserInitializationHelper,
        "wait_for_browser_window_id_silently",
        AsyncMock(side_effect=playwright_error),
    )
    autoload_used = MagicMock(return_value=True)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        autoload_used,
    )

    env = BrowserEnvironment(
        auth_headers={"x-api-key": "test-key"},
        config=BrowserConfig(interactive=False),
    )
    console_print = MagicMock()
    monkeypatch.setattr(env._console, "print", console_print)

    expected_error = (
        environment_module._BrowserAutoloadRestartRequired
        if restart_on_autoload_failure
        else SystemExit
    )
    with pytest.raises(expected_error) as exc_info:
        await env._wait_for_browser_window_id_with_lazy_login(
            AsyncMock(),
            env._config,
            "https://app.narada.ai/initialize?t=window-tag",
            restart_on_autoload_failure=restart_on_autoload_failure,
        )

    assert console_print.call_args_list[0].args == (
        "\n[bold red]> Playwright error:[/bold red]",
        playwright_error,
    )
    if restart_on_autoload_failure:
        assert exc_info.value.__cause__ is playwright_error
        assert console_print.call_count == 1
    else:
        assert exc_info.value.code == 1  # type: ignore[union-attr]
        assert console_print.call_count == 2
        assert "automation page was closed" in console_print.call_args.args[0]
    autoload_used.assert_called_once_with(env._config.extension_id)


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
async def test_open_initialization_uses_target_only_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    playwright_browser = object()
    context = SimpleNamespace(browser=playwright_browser)
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

    assert env._context is context
    assert env._playwright_browser is playwright_browser
    assert env._browser_process_id == 123
    assert env._browser_window_id == "browser-window-123"
    fix_download_behavior.assert_awaited_once_with(context, side_panel_match)  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("interactive", [False, True])
async def test_launch_browser_restarts_once_after_autoload_failure(
    monkeypatch: pytest.MonkeyPatch,
    interactive: bool,
) -> None:
    import narada.environment as environment_module

    config = BrowserConfig(interactive=interactive)
    env = BrowserEnvironment(api_key="test-key", config=config)
    monkeypatch.setattr(environment_module.sys, "platform", "win32")
    autoload_used = MagicMock(return_value=True)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        autoload_used,
    )

    first_process = SimpleNamespace(pid=101)
    second_process = SimpleNamespace(pid=202)
    popen = MagicMock(side_effect=[first_process, second_process])
    monkeypatch.setattr(environment_module.subprocess, "Popen", popen)

    second_result = MagicMock(browser_process_id=202)
    events: list[str] = []

    async def initialize_launched_browser(
        *args: object,
        **kwargs: object,
    ) -> object:
        browser_process_id = kwargs["browser_process_id"]
        events.append(f"initialize-{browser_process_id}")
        if browser_process_id == first_process.pid:
            raise environment_module._BrowserAutoloadRestartRequired(
                "restart first browser"
            )
        return second_result

    async def close_browser_for_autoload_restart(
        _playwright: object,
        browser_config: BrowserConfig,
        browser_process: object,
    ) -> None:
        assert browser_config is config
        events.append(f"close-{browser_process.pid}")  # type: ignore[attr-defined]

    initialize = AsyncMock(side_effect=initialize_launched_browser)
    close_browser = AsyncMock(side_effect=close_browser_for_autoload_restart)
    monkeypatch.setattr(env, "_initialize_launched_browser", initialize)
    monkeypatch.setattr(env, "_close_browser_for_autoload_restart", close_browser)
    logger_info = MagicMock()
    monkeypatch.setattr(environment_module.logger, "info", logger_info)
    console_print = MagicMock()
    monkeypatch.setattr(env._console, "print", console_print)

    result = await env._launch_browser(object(), config)  # type: ignore[arg-type]

    assert result is second_result
    assert result.browser_process_id == 202
    assert events == ["initialize-101", "close-101", "initialize-202"]
    assert popen.call_count == 2
    autoload_used.assert_called_once_with(config.extension_id)
    if interactive:
        assert "Restarting Chrome" in console_print.call_args.args[0]
        logger_info.assert_not_called()
    else:
        console_print.assert_not_called()
        logger_info.assert_called_once()
    first_url = initialize.await_args_list[0].kwargs["tagged_initialization_url"]
    second_url = initialize.await_args_list[1].kwargs["tagged_initialization_url"]
    assert first_url.startswith(f"{config.initialization_url}?t=")
    assert second_url.startswith(f"{config.initialization_url}?t=")
    assert first_url != second_url
    assert initialize.await_args_list[0].kwargs["restart_on_autoload_failure"] is True
    assert initialize.await_args_list[1].kwargs["restart_on_autoload_failure"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("autoload_used", [False, True])
async def test_launch_browser_never_attempts_a_third_launch(
    monkeypatch: pytest.MonkeyPatch,
    autoload_used: bool,
) -> None:
    import narada.environment as environment_module

    config = BrowserConfig(interactive=False)
    env = BrowserEnvironment(api_key="test-key", config=config)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        MagicMock(return_value=autoload_used),
    )
    restart_error = environment_module._BrowserAutoloadRestartRequired("restart")
    final_error = NaradaTimeoutError("Timed out waiting for Narada side panel page")
    launch_once = AsyncMock(
        side_effect=[restart_error, final_error] if autoload_used else restart_error
    )
    monkeypatch.setattr(env, "_launch_browser_once", launch_once)

    expected_error = final_error if autoload_used else restart_error
    with pytest.raises(type(expected_error)) as exc_info:
        await env._launch_browser(object(), config)  # type: ignore[arg-type]

    assert exc_info.value is expected_error
    assert launch_once.await_count == (2 if autoload_used else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initialization_error",
    [
        NaradaExtensionUnauthenticatedError("authentication failed"),
        NaradaUnsupportedBrowserError("unsupported browser"),
        NaradaTimeoutError("generic initialization timeout"),
        ValueError("invalid proxy configuration"),
    ],
)
async def test_launch_browser_does_not_restart_unrelated_initialization_failures(
    monkeypatch: pytest.MonkeyPatch,
    initialization_error: Exception,
) -> None:
    import narada.environment as environment_module

    config = BrowserConfig(interactive=False)
    env = BrowserEnvironment(api_key="test-key", config=config)
    monkeypatch.setattr(
        environment_module,
        "is_win_extension_autoload_used",
        MagicMock(return_value=True),
    )
    launch_once = AsyncMock(side_effect=initialization_error)
    monkeypatch.setattr(env, "_launch_browser_once", launch_once)

    with pytest.raises(type(initialization_error)) as exc_info:
        await env._launch_browser(object(), config)  # type: ignore[arg-type]

    assert exc_info.value is initialization_error
    launch_once.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cdp_error", "wait_side_effect", "expected_terminate"),
    [
        (False, [None], False),
        (False, [subprocess.TimeoutExpired("chrome", 5), None], True),
        (True, [None], True),
    ],
)
async def test_close_browser_for_autoload_restart_uses_terminate_fallback(
    monkeypatch: pytest.MonkeyPatch,
    cdp_error: bool,
    wait_side_effect: list[object],
    expected_terminate: bool,
) -> None:
    config = BrowserConfig(interactive=False)
    env = BrowserEnvironment(
        api_key="test-key",
        config=config,
    )
    cdp_session = AsyncMock()
    if cdp_error:
        cdp_session.send.side_effect = RuntimeError("CDP close failed")
    browser = AsyncMock()
    browser.new_browser_cdp_session.return_value = cdp_session
    playwright = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser))
    )
    process = MagicMock(pid=123)
    process.poll.return_value = None
    process.wait.side_effect = wait_side_effect

    await env._close_browser_for_autoload_restart(  # type: ignore[arg-type]
        playwright,
        config,
        process,
    )

    playwright.chromium.connect_over_cdp.assert_awaited_once_with(config.cdp_url)
    cdp_session.send.assert_awaited_once_with("Browser.close")
    assert process.terminate.called is expected_terminate
    assert process.wait.call_count == len(wait_side_effect)


@pytest.mark.asyncio
async def test_reset_agent_state_rediscovers_side_panel_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    side_panel_url = (
        "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
        "sidepanel.html?browserWindowId=browser-window-123"
    )

    class Page:
        def __init__(self, url: str) -> None:
            self.url = url
            self.reload = AsyncMock()

    class Context:
        def __init__(self, pages: list[Page]) -> None:
            self.pages = pages
            self.browser: Browser | None = None

    class Browser:
        def __init__(self, contexts: list[Context]) -> None:
            self.contexts = contexts
            for context in contexts:
                context.browser = self

    replacement_page = Page(side_panel_url)
    context = Context([replacement_page])
    Browser([context])

    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    env._initialized = True
    env._browser_window_id = "browser-window-123"
    env._context = context  # type: ignore[assignment]
    ensure_playwright_connected = AsyncMock()
    stop_playwright = AsyncMock()
    monkeypatch.setattr(
        env, "_ensure_playwright_connected", ensure_playwright_connected
    )
    monkeypatch.setattr(env, "_stop_playwright", stop_playwright)

    await env.reset_agent_state()

    replacement_page.reload.assert_awaited_once()
    ensure_playwright_connected.assert_awaited_once()
    stop_playwright.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_agent_state_rediscovers_side_panel_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    class Browser:
        contexts: list[object] = []

    class Context:
        browser = Browser()

    side_panel_match = environment_module._SidePanelMatch(
        page=None,
        target_id="replacement-target-123",
        browser_context_id="browser-context-123",
    )
    find_side_panel_match = AsyncMock(return_value=side_panel_match)
    monkeypatch.setattr(
        environment_module,
        "_find_side_panel_match",
        find_side_panel_match,
    )

    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    env._initialized = True
    env._browser_window_id = "browser-window-123"
    context = Context()
    env._context = context  # type: ignore[assignment]
    ensure_playwright_connected = AsyncMock()
    stop_playwright = AsyncMock()
    monkeypatch.setattr(
        env, "_ensure_playwright_connected", ensure_playwright_connected
    )
    monkeypatch.setattr(env, "_stop_playwright", stop_playwright)
    reload_side_panel_target = AsyncMock()
    monkeypatch.setattr(
        env,
        "_reload_side_panel_target",
        reload_side_panel_target,
    )

    await env.reset_agent_state()

    find_side_panel_match.assert_awaited_once_with(
        context.browser,
        "chrome-extension://bhioaidlggjdkheaajakomifblpjmokn/"
        "sidepanel.html?browserWindowId=browser-window-123",
    )
    reload_side_panel_target.assert_awaited_once_with(
        context,
        "replacement-target-123",
    )
    ensure_playwright_connected.assert_awaited_once()
    stop_playwright.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_agent_state_rejects_missing_current_side_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    class Browser:
        contexts: list[object] = []

    class Context:
        browser = Browser()

    find_side_panel_match = AsyncMock(return_value=None)
    monkeypatch.setattr(
        environment_module,
        "_find_side_panel_match",
        find_side_panel_match,
    )
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    env._initialized = True
    env._browser_window_id = "browser-window-123"
    env._context = Context()  # type: ignore[assignment]
    ensure_playwright_connected = AsyncMock()
    stop_playwright = AsyncMock()
    monkeypatch.setattr(
        env, "_ensure_playwright_connected", ensure_playwright_connected
    )
    monkeypatch.setattr(env, "_stop_playwright", stop_playwright)

    with pytest.raises(NaradaInitializationError, match="no longer available"):
        await env.reset_agent_state()

    ensure_playwright_connected.assert_awaited_once()
    stop_playwright.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_agent_state_bounds_discovery_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    class CdpSession:
        def __init__(self) -> None:
            self.never = asyncio.Event()
            self.detach_started = asyncio.Event()

        async def send(self, method: str) -> dict[str, Any]:
            assert method == "Target.getTargets"
            await self.never.wait()
            return {}

        async def detach(self) -> None:
            self.detach_started.set()
            await self.never.wait()

    class Browser:
        def __init__(self) -> None:
            self.contexts: list[object] = []
            self.cdp_session = CdpSession()

        async def new_browser_cdp_session(self) -> CdpSession:
            return self.cdp_session

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    monkeypatch.setattr(environment_module, "_SIDE_PANEL_RESET_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(environment_module, "_CDP_CLEANUP_TIMEOUT_SECONDS", 0.01)
    context = Context()
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    env._initialized = True
    env._browser_window_id = "browser-window-123"
    env._context = context  # type: ignore[assignment]
    ensure_playwright_connected = AsyncMock()
    stop_playwright = AsyncMock()
    monkeypatch.setattr(
        env, "_ensure_playwright_connected", ensure_playwright_connected
    )
    monkeypatch.setattr(env, "_stop_playwright", stop_playwright)

    with pytest.raises(NaradaTimeoutError, match="Timed out resetting"):
        await asyncio.wait_for(env.reset_agent_state(), timeout=0.5)

    assert context.browser.cdp_session.detach_started.is_set()
    ensure_playwright_connected.assert_awaited_once()
    stop_playwright.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_agent_state_bounds_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    never = asyncio.Event()

    async def wait_forever() -> None:
        await never.wait()

    monkeypatch.setattr(environment_module, "_SIDE_PANEL_RESET_TIMEOUT_SECONDS", 0.01)
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    env._initialized = True
    env._browser_window_id = "browser-window-123"
    ensure_playwright_connected = AsyncMock(side_effect=wait_forever)
    stop_playwright = AsyncMock()
    monkeypatch.setattr(
        env, "_ensure_playwright_connected", ensure_playwright_connected
    )
    monkeypatch.setattr(env, "_stop_playwright", stop_playwright)

    with pytest.raises(NaradaTimeoutError, match="Timed out resetting"):
        await asyncio.wait_for(env.reset_agent_state(), timeout=0.5)

    ensure_playwright_connected.assert_awaited_once()
    stop_playwright.assert_awaited_once()


class _TargetCdpSession:
    def __init__(
        self,
        *,
        reload_error: bool = False,
        lifecycle_before_reload_response: bool = False,
        detach_during_reload: bool = False,
    ) -> None:
        self.reload_error = reload_error
        self.lifecycle_before_reload_response = lifecycle_before_reload_response
        self.detach_during_reload = detach_during_reload
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.nested_messages: list[dict[str, Any]] = []
        self.handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self.reload_sent = asyncio.Event()
        self.allow_reload_response = asyncio.Event()
        self.detached = False

    def on(self, event: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(
        self, event: str, handler: Callable[[dict[str, Any]], None]
    ) -> None:
        self.handlers[event].remove(handler)

    def emit(self, event: str, params: dict[str, Any]) -> None:
        for handler in list(self.handlers.get(event, [])):
            handler(params)

    def emit_target_message(self, message: dict[str, Any]) -> None:
        self.emit(
            "Target.receivedMessageFromTarget",
            {
                "sessionId": "target-session-123",
                "message": json.dumps(message),
            },
        )

    async def send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.commands.append((method, params))
        if method == "Target.attachToTarget":
            return {"sessionId": "target-session-123"}
        if method != "Target.sendMessageToTarget":
            return {}

        nested_message = json.loads(params["message"])
        nested_method = nested_message["method"]
        self.nested_messages.append(nested_message)
        if nested_method == "Page.getFrameTree":
            result: dict[str, Any] = {
                "frameTree": {
                    "frame": {
                        "id": "main-frame-123",
                        "loaderId": "old-loader-123",
                    }
                }
            }
        else:
            result = {}

        if nested_method == "Page.reload" and self.detach_during_reload:
            self.reload_sent.set()
            self.emit(
                "Target.detachedFromTarget",
                {"sessionId": "target-session-123"},
            )
            return {}

        if nested_method == "Page.reload" and self.lifecycle_before_reload_response:
            self.emit_target_message(
                {
                    "method": "Page.lifecycleEvent",
                    "params": {
                        "name": "load",
                        "frameId": "main-frame-123",
                        "loaderId": "new-loader-123",
                    },
                }
            )
            self.reload_sent.set()
            await self.allow_reload_response.wait()

        if nested_method == "Page.reload" and self.reload_error:
            response = {
                "id": nested_message["id"],
                "error": {"code": -32000, "message": "reload failed"},
            }
        else:
            response = {"id": nested_message["id"], "result": result}

        self.emit_target_message(response)
        if nested_method == "Page.reload":
            self.reload_sent.set()
        return {}

    async def detach(self) -> None:
        self.detached = True


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle_before_reload_response", [False, True])
async def test_reload_side_panel_target_waits_for_response_and_new_loader(
    lifecycle_before_reload_response: bool,
) -> None:
    class Browser:
        def __init__(self) -> None:
            self.cdp_session = _TargetCdpSession(
                lifecycle_before_reload_response=lifecycle_before_reload_response
            )

        async def new_browser_cdp_session(self) -> _TargetCdpSession:
            return self.cdp_session

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    context = Context()
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    reload_task = asyncio.create_task(
        env._reload_side_panel_target(context, "target-123")  # type: ignore[arg-type]
    )
    try:
        await asyncio.wait_for(
            context.browser.cdp_session.reload_sent.wait(), timeout=1
        )
        await asyncio.sleep(0)

        assert not reload_task.done()

        if lifecycle_before_reload_response:
            context.browser.cdp_session.allow_reload_response.set()
        else:
            invalid_lifecycle_params = [
                {
                    "name": "DOMContentLoaded",
                    "frameId": "main-frame-123",
                    "loaderId": "new-loader-123",
                },
                {
                    "name": "load",
                    "frameId": "other-frame-123",
                    "loaderId": "new-loader-123",
                },
                {
                    "name": "load",
                    "frameId": "main-frame-123",
                    "loaderId": "old-loader-123",
                },
            ]
            for lifecycle_params in invalid_lifecycle_params:
                context.browser.cdp_session.emit_target_message(
                    {
                        "method": "Page.lifecycleEvent",
                        "params": lifecycle_params,
                    }
                )
                await asyncio.sleep(0)
                assert not reload_task.done()

            context.browser.cdp_session.emit_target_message(
                {
                    "method": "Page.lifecycleEvent",
                    "params": {
                        "name": "load",
                        "frameId": "main-frame-123",
                        "loaderId": "new-loader-123",
                    },
                }
            )

        await asyncio.wait_for(reload_task, timeout=1)
    finally:
        if not reload_task.done():
            reload_task.cancel()
            await asyncio.gather(reload_task, return_exceptions=True)

    assert [
        message["method"] for message in context.browser.cdp_session.nested_messages
    ] == [
        "Page.enable",
        "Page.getFrameTree",
        "Page.setLifecycleEventsEnabled",
        "Page.reload",
    ]
    assert context.browser.cdp_session.nested_messages[2]["params"] == {"enabled": True}
    assert context.browser.cdp_session.nested_messages[3]["params"] == {
        "loaderId": "old-loader-123"
    }
    assert context.browser.cdp_session.commands[0] == (
        "Target.attachToTarget",
        {"targetId": "target-123", "flatten": False},
    )
    assert context.browser.cdp_session.commands[-1] == (
        "Target.detachFromTarget",
        {"sessionId": "target-session-123"},
    )
    assert context.browser.cdp_session.detached
    assert all(
        not handlers for handlers in context.browser.cdp_session.handlers.values()
    )


@pytest.mark.asyncio
async def test_reload_side_panel_target_surfaces_nested_error() -> None:
    class Browser:
        def __init__(self) -> None:
            self.cdp_session = _TargetCdpSession(reload_error=True)

        async def new_browser_cdp_session(self) -> _TargetCdpSession:
            return self.cdp_session

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    context = Context()
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    with pytest.raises(NaradaInitializationError, match="CDP Page.reload failed"):
        await env._reload_side_panel_target(  # type: ignore[arg-type]
            context,
            "target-123",
        )

    assert context.browser.cdp_session.commands[-1] == (
        "Target.detachFromTarget",
        {"sessionId": "target-session-123"},
    )
    assert context.browser.cdp_session.detached
    assert all(
        not handlers for handlers in context.browser.cdp_session.handlers.values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("detach_during_reload", [True, False])
async def test_reload_side_panel_target_surfaces_target_detachment(
    detach_during_reload: bool,
) -> None:
    class Browser:
        def __init__(self) -> None:
            self.cdp_session = _TargetCdpSession(
                detach_during_reload=detach_during_reload
            )

        async def new_browser_cdp_session(self) -> _TargetCdpSession:
            return self.cdp_session

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    context = Context()
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    reload_task = asyncio.create_task(
        env._reload_side_panel_target(context, "target-123")  # type: ignore[arg-type]
    )

    try:
        await asyncio.wait_for(
            context.browser.cdp_session.reload_sent.wait(), timeout=1
        )
        if not detach_during_reload:
            context.browser.cdp_session.emit(
                "Target.detachedFromTarget",
                {"sessionId": "target-session-123"},
            )

        with pytest.raises(NaradaInitializationError, match="detached while reloading"):
            await asyncio.wait_for(reload_task, timeout=1)
    finally:
        if not reload_task.done():
            reload_task.cancel()
            await asyncio.gather(reload_task, return_exceptions=True)

    assert context.browser.cdp_session.detached
    assert all(
        not handlers for handlers in context.browser.cdp_session.handlers.values()
    )


@pytest.mark.asyncio
async def test_reload_side_panel_target_times_out_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.environment as environment_module

    class Browser:
        def __init__(self) -> None:
            self.cdp_session = _TargetCdpSession()

        async def new_browser_cdp_session(self) -> _TargetCdpSession:
            return self.cdp_session

    class Context:
        def __init__(self) -> None:
            self.browser = Browser()

    monkeypatch.setattr(environment_module, "_SIDE_PANEL_RESET_TIMEOUT_SECONDS", 0.01)
    context = Context()
    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )

    with pytest.raises(NaradaTimeoutError, match="side panel to reload"):
        await asyncio.wait_for(
            env._reload_side_panel_target(  # type: ignore[arg-type]
                context,
                "target-123",
            ),
            timeout=0.5,
        )

    assert context.browser.cdp_session.detached
    assert all(
        not handlers for handlers in context.browser.cdp_session.handlers.values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("contexts_result", "expected_download_params"),
    [
        (
            {
                "browserContextIds": [],
                "defaultBrowserContextId": "browser-context-123",
            },
            {"behavior": "default"},
        ),
        (
            {
                "browserContextIds": ["browser-context-123"],
                "defaultBrowserContextId": "default-context-123",
            },
            {
                "behavior": "default",
                "browserContextId": "browser-context-123",
            },
        ),
        (
            {"browserContextIds": []},
            {"behavior": "default"},
        ),
    ],
)
async def test_fix_download_behavior_scopes_browser_context(
    contexts_result: dict[str, Any],
    expected_download_params: dict[str, str],
) -> None:
    import narada.environment as environment_module

    class BrowserCdpSession:
        def __init__(self) -> None:
            self.commands: list[tuple[str, dict[str, Any]]] = []
            self.detached = False

        async def send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
            self.commands.append((method, params))
            if method == "Target.getBrowserContexts":
                return contexts_result
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
        ("Target.getBrowserContexts", {}),
        (
            "Browser.setDownloadBehavior",
            expected_download_params,
        ),
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
@pytest.mark.parametrize(
    ("contexts_result", "expected_download_params"),
    [
        (
            {
                "browserContextIds": [],
                "defaultBrowserContextId": "browser-context-123",
            },
            {"behavior": "default"},
        ),
        (
            {
                "browserContextIds": ["browser-context-123"],
                "defaultBrowserContextId": "default-context-123",
            },
            {
                "behavior": "default",
                "browserContextId": "browser-context-123",
            },
        ),
    ],
)
async def test_fix_download_behavior_does_not_retry_unscoped_after_failure(
    contexts_result: dict[str, Any],
    expected_download_params: dict[str, str],
) -> None:
    import narada.environment as environment_module

    class BrowserCdpSession:
        def __init__(self) -> None:
            self.commands: list[tuple[str, dict[str, Any]]] = []
            self.detached = False

        async def send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
            self.commands.append((method, params))
            if method == "Target.getBrowserContexts":
                return contexts_result
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

    assert context.browser.cdp_session.commands == [
        ("Target.getBrowserContexts", {}),
        ("Browser.setDownloadBehavior", expected_download_params),
    ]
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
    monkeypatch.setattr(environment_module.sys, "platform", "linux")
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


@pytest.mark.asyncio
@pytest.mark.parametrize("side_panel_appears", [True, False])
async def test_launch_browser_does_not_reread_known_browser_window_id(
    monkeypatch: pytest.MonkeyPatch,
    side_panel_appears: bool,
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
    monkeypatch.setattr(environment_module.sys, "platform", "linux")
    monkeypatch.setattr(environment_module.asyncio, "sleep", AsyncMock())

    env = BrowserEnvironment(
        api_key="test-key", config=BrowserConfig(interactive=False)
    )
    wait_for_browser_window_id = AsyncMock(return_value="browser-window-123")
    monkeypatch.setattr(
        env,
        "_wait_for_browser_window_id_with_lazy_login",
        wait_for_browser_window_id,
    )
    side_panel_match = environment_module._SidePanelMatch(
        page=None,
        target_id="target-123",
        browser_context_id="browser-context-123",
    )
    find_side_panel_match = AsyncMock(
        side_effect=(
            [None, None, side_panel_match] if side_panel_appears else [None] * 10
        )
    )
    monkeypatch.setattr(
        environment_module,
        "_find_side_panel_match",
        find_side_panel_match,
    )
    playwright = Playwright(state)

    if side_panel_appears:
        result = await env._launch_browser(  # type: ignore[arg-type]
            playwright,
            env._config,
        )
        assert result.side_panel_match is side_panel_match
    else:
        with pytest.raises(NaradaTimeoutError, match="side panel page"):
            await env._launch_browser(  # type: ignore[arg-type]
                playwright,
                env._config,
            )

    wait_for_browser_window_id.assert_awaited_once()
    assert playwright.chromium.connect_count == (3 if side_panel_appears else 10)

    if not side_panel_appears:
        wait_for_browser_window_id.reset_mock()
        find_side_panel_match.reset_mock(side_effect=True)
        find_side_panel_match.side_effect = [None] * 10
        playwright.chromium.connect_count = 0

        with pytest.raises(environment_module._BrowserAutoloadRestartRequired):
            await env._initialize_launched_browser(  # type: ignore[arg-type]
                playwright,
                env._config,
                browser_process_id=123,
                tagged_initialization_url=state["initialization_url"],
                proxy_requires_auth=False,
                restart_on_autoload_failure=True,
            )

        wait_for_browser_window_id.assert_awaited_once()
        assert find_side_panel_match.await_count == 10
        assert playwright.chromium.connect_count == 10

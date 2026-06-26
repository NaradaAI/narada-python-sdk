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

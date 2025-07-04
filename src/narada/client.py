from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from typing import Any, TypedDict
from uuid import uuid4

from playwright.async_api import (
    ElementHandle,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.async_api._context_manager import PlaywrightContextManager

from narada.config import BrowserConfig
from narada.errors import (
    NaradaExtensionMissingError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)
from narada.utils import assert_never
from narada.window import BrowserWindow, create_side_panel_url


class _CreateSubprocessExtraArgs(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


class Narada:
    _BROWSER_WINDOW_ID_SELECTOR = "#narada-browser-window-id"
    _UNSUPPORTED_BROWSER_INDICATOR_SELECTOR = "#narada-unsupported-browser"
    _EXTENSION_MISSING_INDICATOR_SELECTOR = "#narada-extension-missing"
    _INITIALIZATION_ERROR_INDICATOR_SELECTOR = "#narada-initialization-error"

    _api_key: str
    _playwright_context_manager: PlaywrightContextManager | None = None
    _playwright: Playwright | None = None

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ["NARADA_API_KEY"]

    async def __aenter__(self) -> Narada:
        self._playwright_context_manager = async_playwright()
        self._playwright = await self._playwright_context_manager.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._playwright_context_manager is None:
            return

        await self._playwright_context_manager.__aexit__(*args)
        self._playwright_context_manager = None
        self._playwright = None

    async def open_and_initialize_browser_window(
        self, config: BrowserConfig | None = None
    ) -> BrowserWindow:
        assert self._playwright is not None
        playwright = self._playwright

        config = config or BrowserConfig()

        # A unique tag is appened to the initialization URL we that we can find the new page that
        # was opened, since otherwise when more than one initialization page is opened in the same
        # browser instance, we wouldn't be able to tell them apart.
        window_tag = uuid4().hex
        tagged_initialization_url = f"{config.initialization_url}?t={window_tag}"

        browser_args = [
            f"--user-data-dir={config.user_data_dir}",
            f"--profile-directory={config.profile_directory}",
            f"--remote-debugging-port={config.cdp_port}",
            "--new-window",
            tagged_initialization_url,
            # TODO: This is needed if we don't use CDP but let Playwright manage the browser.
            # "--disable-blink-features=AutomationControlled",
        ]

        # OS-dependent arguments to create the browser process as a detached, independent process.
        extra_args: _CreateSubprocessExtraArgs
        if sys.platform == "win32":
            extra_args = {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
            }
        else:
            extra_args = {
                "start_new_session": True,
            }

        # Launch an independent browser process which will not be killed when the current program
        # exits.
        browser_process = await asyncio.create_subprocess_exec(
            config.executable_path,
            *browser_args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **extra_args,
        )

        logging.debug("Browser process started with PID: %s", browser_process.pid)

        # Give the browser some time to start up.
        await asyncio.sleep(3)

        max_cdp_connect_attempts = 3
        for attempt in range(max_cdp_connect_attempts):
            try:
                browser = await playwright.chromium.connect_over_cdp(
                    f"http://localhost:{config.cdp_port}"
                )
            except Exception:
                if attempt == max_cdp_connect_attempts - 1:
                    raise
                await asyncio.sleep(3)
                continue

        # Grab the browser window ID from the page we just opened.
        context = browser.contexts[0]
        initialization_page = next(
            p for p in context.pages if p.url == tagged_initialization_url
        )
        browser_window_id = await self._wait_for_browser_window_id(initialization_page)

        # Revert the download behavior to the default behavior for the extension, otherwise our
        # extension cannot download files.
        side_panel_url = create_side_panel_url(config, browser_window_id)
        side_panel_page = next(p for p in context.pages if p.url == side_panel_url)
        cdp_session = await side_panel_page.context.new_cdp_session(side_panel_page)
        await cdp_session.send("Page.setDownloadBehavior", {"behavior": "default"})
        await cdp_session.detach()

        return BrowserWindow(
            api_key=self._api_key,
            config=config,
            context=context,
            id=browser_window_id,
        )

    @staticmethod
    async def _wait_for_selector_attached(
        page: Page, selector: str, *, timeout: int
    ) -> ElementHandle | None:
        try:
            return await page.wait_for_selector(
                selector, state="attached", timeout=timeout
            )
        except PlaywrightTimeoutError:
            return None

    @staticmethod
    async def _wait_for_browser_window_id(page: Page, *, timeout: int = 15_000) -> str:
        selectors = [
            Narada._BROWSER_WINDOW_ID_SELECTOR,
            Narada._UNSUPPORTED_BROWSER_INDICATOR_SELECTOR,
            Narada._EXTENSION_MISSING_INDICATOR_SELECTOR,
            Narada._INITIALIZATION_ERROR_INDICATOR_SELECTOR,
        ]
        tasks: list[asyncio.Task[ElementHandle | None]] = [
            asyncio.create_task(
                Narada._wait_for_selector_attached(page, selector, timeout=timeout)
            )
            for selector in selectors
        ]
        (
            browser_window_id_task,
            unsupported_browser_indicator_task,
            extension_missing_indicator_task,
            initialization_error_indicator_task,
        ) = tasks

        done, pending = await asyncio.wait(
            tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        if len(done) == 0:
            raise NaradaTimeoutError("Timed out waiting for browser window ID")

        for task in done:
            if task == browser_window_id_task:
                browser_window_id_elem = task.result()
                if browser_window_id_elem is None:
                    raise NaradaTimeoutError("Timed out waiting for browser window ID")

                browser_window_id = await browser_window_id_elem.text_content()
                if browser_window_id is None:
                    raise NaradaInitializationError("Browser window ID is empty")

                return browser_window_id

            # TODO: Create custom exception types for these cases.
            if task == unsupported_browser_indicator_task and task.result() is not None:
                raise NaradaUnsupportedBrowserError("Unsupported browser")

            if task == extension_missing_indicator_task and task.result() is not None:
                raise NaradaExtensionMissingError("Narada extension missing")

            if (
                task == initialization_error_indicator_task
                and task.result() is not None
            ):
                raise NaradaInitializationError("Initialization error")

        assert_never()

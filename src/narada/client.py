from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, TypedDict
from uuid import uuid4

from playwright._impl._errors import TargetClosedError
from playwright.async_api import (
    Browser,
    ElementHandle,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.async_api._context_manager import PlaywrightContextManager
from rich.console import Console

from narada.config import BrowserConfig
from narada.errors import (
    NaradaExtensionMissingError,
    NaradaExtensionUnauthenticatedError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)
from narada.utils import assert_never
from narada.window import BrowserWindow, create_side_panel_url


class _CreateSubprocessExtraArgs(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


@dataclass
class _LaunchBrowserResult:
    browser_window_id: str
    side_panel_page: Page


class _ShouldRetryCreateProcess(Exception):
    browser: Browser
    browser_process: asyncio.subprocess.Process

    def __init__(
        self, browser: Browser, browser_process: asyncio.subprocess.Process
    ) -> None:
        super().__init__()
        self.browser = browser
        self.browser_process = browser_process


class Narada:
    _BROWSER_WINDOW_ID_SELECTOR = "#narada-browser-window-id"
    _UNSUPPORTED_BROWSER_INDICATOR_SELECTOR = "#narada-unsupported-browser"
    _EXTENSION_MISSING_INDICATOR_SELECTOR = "#narada-extension-missing"
    _EXTENSION_UNAUTHENTICATED_INDICATOR_SELECTOR = "#narada-extension-unauthenticated"
    _INITIALIZATION_ERROR_INDICATOR_SELECTOR = "#narada-initialization-error"

    _api_key: str
    _console: Console
    _playwright_context_manager: PlaywrightContextManager | None = None
    _playwright: Playwright | None = None

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ["NARADA_API_KEY"]
        self._console = Console()

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

        launch_browser_result = None
        while launch_browser_result is None:
            try:
                launch_browser_result = await self._launch_browser(playwright, config)
            except _ShouldRetryCreateProcess as e:
                if config.interactive:
                    self._console.input(
                        "\n:wrench: [bold blue]New extension installation detected. Press Enter to "
                        "relaunch the browser and continue.[/bold blue]"
                    )

                # Close the CDP connection to the browser.
                await e.browser.close()

                # Gracefully terminate the browser process.
                e.browser_process.terminate()
                await e.browser_process.wait()

        side_panel_page = launch_browser_result.side_panel_page
        browser_window_id = launch_browser_result.browser_window_id

        cdp_session = await side_panel_page.context.new_cdp_session(side_panel_page)
        await cdp_session.send("Page.setDownloadBehavior", {"behavior": "default"})
        await cdp_session.detach()

        return BrowserWindow(
            api_key=self._api_key,
            config=config,
            context=side_panel_page.context,
            id=browser_window_id,
        )

    async def _launch_browser(
        self, playwright: Playwright, config: BrowserConfig
    ) -> _LaunchBrowserResult:
        # A unique tag is appended to the initialization URL so that we can find the new page that
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

        max_cdp_connect_attempts = 10
        for attempt in range(max_cdp_connect_attempts):
            try:
                browser = await playwright.chromium.connect_over_cdp(
                    f"http://localhost:{config.cdp_port}"
                )
            except Exception:
                # The browser process might not be immediately ready to accept CDP connections.
                # Retry a few times before giving up.
                if attempt == max_cdp_connect_attempts - 1:
                    raise
                await asyncio.sleep(3)
                continue

        # Grab the browser window ID from the page we just opened.
        context = browser.contexts[0]
        initialization_page = next(
            p for p in context.pages if p.url == tagged_initialization_url
        )

        # Wait for the browser window ID to be available, potentially letting the user respond to
        # recoverable errors interactively.
        if config.interactive:
            browser_window_id = await self._wait_for_browser_window_id_interactively(
                initialization_page
            )
        else:
            browser_window_id = await Narada._wait_for_browser_window_id(
                initialization_page,
            )

        # Revert the download behavior to the default behavior for the extension, otherwise our
        # extension cannot download files.
        side_panel_url = create_side_panel_url(config, browser_window_id)
        side_panel_page = next(
            (p for p in context.pages if p.url == side_panel_url), None
        )
        if side_panel_page is None:
            raise _ShouldRetryCreateProcess(browser, browser_process)

        if config.interactive:
            self._console.print(
                "\n:rocket: Initialization successful. Browser window ID: "
                f"{browser_window_id}\n",
                style="bold green",
            )

        return _LaunchBrowserResult(
            browser_window_id=browser_window_id,
            side_panel_page=side_panel_page,
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
            Narada._EXTENSION_UNAUTHENTICATED_INDICATOR_SELECTOR,
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
            extension_unauthenticated_indicator_task,
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
                task == extension_unauthenticated_indicator_task
                and task.result() is not None
            ):
                raise NaradaExtensionUnauthenticatedError(
                    "Sign in to the Narada extension first"
                )

            if (
                task == initialization_error_indicator_task
                and task.result() is not None
            ):
                raise NaradaInitializationError("Initialization error")

        assert_never()

    async def _wait_for_browser_window_id_interactively(
        self, page: Page, *, per_attempt_timeout: int = 15_000
    ) -> str:
        try:
            while True:
                try:
                    return await Narada._wait_for_browser_window_id(
                        page, timeout=per_attempt_timeout
                    )
                except NaradaExtensionMissingError:
                    self._console.input(
                        "\n:wrench: [bold blue]The Narada Enterprise extension is not installed. "
                        "Please follow the instructions in the browser window to install it first, "
                        "then press Enter to continue.[/bold blue]",
                    )
                except NaradaExtensionUnauthenticatedError:
                    self._console.input(
                        "\n:lock: [bold blue]Please sign in to the Narada extension first, then "
                        "press Enter to continue.[/bold blue]",
                    )

                # Bring the page to the front and wait a little bit before refreshing it, as this
                # page needs to be the active tab in order to automatically open the side panel.
                await page.bring_to_front()
                await asyncio.sleep(0.1)
                await page.reload()

        except TargetClosedError:
            self._console.print(
                "\n:warning: It seems the Narada automation page was closed. Please retry the "
                "action and keep the Narada web page open.",
                style="bold red",
            )
            sys.exit(1)

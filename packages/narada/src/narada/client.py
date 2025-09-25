from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from narada_core.errors import (
    NaradaExtensionMissingError,
    NaradaExtensionUnauthenticatedError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)
from playwright._impl._errors import Error as PlaywrightError
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
from rich.console import Console

from narada.config import BrowserConfig
from narada.utils import assert_never
from narada.window import LocalBrowserWindow, create_side_panel_url


@dataclass
class _LaunchBrowserResult:
    browser_process_id: int
    browser_window_id: str
    side_panel_page: Page


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
    ) -> LocalBrowserWindow:
        assert self._playwright is not None
        playwright = self._playwright

        config = config or BrowserConfig()

        launch_browser_result = await self._launch_browser(playwright, config)
        side_panel_page = launch_browser_result.side_panel_page
        browser_window_id = launch_browser_result.browser_window_id

        await self._fix_download_behavior(side_panel_page)

        return LocalBrowserWindow(
            api_key=self._api_key,
            browser_process_id=launch_browser_result.browser_process_id,
            browser_window_id=browser_window_id,
            config=config,
            context=side_panel_page.context,
        )

    async def initialize_in_existing_browser_window(
        self, config: BrowserConfig | None = None
    ) -> LocalBrowserWindow:
        """Initializes the Narada extension in an existing browser window.

        This method connects to an existing browser process via CDP and performs the same
        initialization logic as `open_and_initialize_browser_window`, but without launching a new
        browser process.
        """
        assert self._playwright is not None
        playwright = self._playwright

        config = config or BrowserConfig()

        browser = await playwright.chromium.connect_over_cdp(config.cdp_url)

        # Generate a unique tag for the initialization URL
        window_tag = uuid4().hex
        tagged_initialization_url = f"{config.initialization_url}?t={window_tag}"

        # Open the initialization page in a new tab in the default context.
        context = browser.contexts[0]
        initialization_page = await context.new_page()
        await initialization_page.goto(tagged_initialization_url)

        browser_window_id = await self._wait_for_browser_window_id(
            initialization_page, config
        )

        # Playwright seems unable to pick up the side panel page that is automatically opened by the
        # initialization page. We need to establish a new CDP connection to the browser *after* the
        # side panel page is opened for Playwright to see it.
        await browser.close()
        browser = await playwright.chromium.connect_over_cdp(config.cdp_url)
        context = browser.contexts[0]

        side_panel_url = create_side_panel_url(config, browser_window_id)
        side_panel_page = next(p for p in context.pages if p.url == side_panel_url)

        await self._fix_download_behavior(side_panel_page)

        if config.interactive:
            self._print_success_message(browser_window_id)

        return LocalBrowserWindow(
            api_key=self._api_key,
            browser_process_id=None,
            browser_window_id=browser_window_id,
            config=config,
            context=context,
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
            "--no-default-browser-check",
            "--no-first-run",
            "--new-window",
            tagged_initialization_url,
            # TODO: This is needed if we don't use CDP but let Playwright manage the browser.
            # "--disable-blink-features=AutomationControlled",
        ]

        # Launch an independent browser process which will not be killed when the current program
        # exits.
        if sys.platform == "win32":
            browser_process = subprocess.Popen(
                [config.executable_path, *browser_args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS,
            )
        else:
            browser_process = await asyncio.create_subprocess_exec(
                config.executable_path,
                *browser_args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )

        logging.debug("Browser process started with PID: %s", browser_process.pid)

        # We need to wait a bit for the initial page to open before connecting to the browser over
        # CDP, otherwise Playwright can see an empty context with no pages.
        await asyncio.sleep(2)

        browser_window_id = None
        side_panel_page = None
        max_cdp_connect_attempts = 10
        for attempt in range(max_cdp_connect_attempts):
            try:
                browser = await playwright.chromium.connect_over_cdp(config.cdp_url)
            except Exception:
                # The browser process might not be immediately ready to accept CDP connections.
                # Retry a few times before giving up.
                if attempt == max_cdp_connect_attempts - 1:
                    raise
                await asyncio.sleep(2)
                continue

            # Grab the browser window ID from the page we just opened.
            context = browser.contexts[0]
            initialization_page = next(
                (p for p in context.pages if p.url == tagged_initialization_url), None
            )
            if initialization_page is not None:
                browser_window_id = await self._wait_for_browser_window_id(
                    initialization_page, config
                )

                side_panel_url = create_side_panel_url(config, browser_window_id)
                side_panel_page = next(
                    (p for p in context.pages if p.url == side_panel_url), None
                )
                if side_panel_page is not None:
                    break

            if attempt == max_cdp_connect_attempts - 1:
                raise NaradaTimeoutError("Timed out waiting for initialization page")

            # Close the current CDP connection and try again.
            await browser.close()
            await asyncio.sleep(3)

        # These are impossible as we would've raised an exception above otherwise.
        assert browser_window_id is not None
        assert side_panel_page is not None

        if config.interactive:
            self._print_success_message(browser_window_id)

        return _LaunchBrowserResult(
            browser_process_id=browser_process.pid,
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
    async def _wait_for_browser_window_id_silently(
        page: Page, *, timeout: int = 15_000
    ) -> str:
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
                    return await Narada._wait_for_browser_window_id_silently(
                        page, timeout=per_attempt_timeout
                    )
                except NaradaExtensionMissingError:
                    self._console.input(
                        "\n[bold]>[/bold] [bold blue]The Narada Enterprise extension is not "
                        "installed. Please follow the instructions in the browser window to "
                        "install it first, then press Enter to continue.[/bold blue]\n",
                    )
                except NaradaExtensionUnauthenticatedError:
                    self._console.input(
                        "\n[bold]>[/bold] [bold blue]Please sign in to the Narada extension first, "
                        "then press Enter to continue.[/bold blue]",
                    )

                # Bring the page to the front and wait a little bit before refreshing it, as this
                # page needs to be the active tab in order to automatically open the side panel.
                await page.bring_to_front()
                await asyncio.sleep(0.1)
                await page.reload()

        except PlaywrightError:
            self._console.print(
                "\n[bold]>[/bold] [bold red]It seems the Narada automation page was closed. Please "
                "retry the action and keep the Narada web page open.[/bold red]",
            )
            sys.exit(1)

    async def _wait_for_browser_window_id(
        self,
        initialization_page: Page,
        config: BrowserConfig,
    ) -> str:
        """Waits for the browser window ID to be available, potentially letting the user respond to
        recoverable errors interactively.
        """
        if config.interactive:
            return await self._wait_for_browser_window_id_interactively(
                initialization_page
            )
        else:
            return await Narada._wait_for_browser_window_id_silently(
                initialization_page
            )

    async def _fix_download_behavior(self, side_panel_page: Page) -> None:
        """Reverts the download behavior to the default behavior for the extension, otherwise our
        extension cannot download files.
        """
        cdp_session = await side_panel_page.context.new_cdp_session(side_panel_page)
        await cdp_session.send("Page.setDownloadBehavior", {"behavior": "default"})
        await cdp_session.detach()

    def _print_success_message(self, browser_window_id: str) -> None:
        self._console.print(
            "\n[bold]>[/bold] [bold green]Initialization successful. Browser window ID: "
            f"{browser_window_id}[/bold green]\n",
        )

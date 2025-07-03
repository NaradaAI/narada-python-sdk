import asyncio
import logging
import os
import subprocess
import sys
from typing import TypedDict
from uuid import uuid4

from playwright.async_api import ElementHandle, Page, async_playwright

from narada.config import BrowserConfig
from narada.errors import (
    NaradaExtensionMissingError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)
from narada.utils import assert_never
from narada.window import BrowserWindow

__version__ = "0.1.0"


class _CreateSubprocessExtraArgs(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


class Narada:
    _BROWSER_WINDOW_ID_SELECTOR = "#narada-browser-window-id"
    _UNSUPPORTED_BROWSER_INDICATOR_SELECTOR = "#narada-unsupported-browser"
    _EXTENSION_MISSING_INDICATOR_SELECTOR = "#narada-extension-missing"
    _INITIALIZATION_ERROR_INDICATOR_SELECTOR = "#narada-initialization-error"

    _api_key: str

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ["NARADA_API_KEY"]

    async def open_and_initialize_browser_window(
        self, config: BrowserConfig | None = None
    ) -> BrowserWindow:
        config = config or BrowserConfig()

        # A unique tag is appened to the initialization URL we that we can find the new page that
        # was opened, since otherwise when more than one initialization page is opened in the same
        # browser instance, we wouldn't be able to tell them apart.
        window_tag = uuid4().hex
        tagged_initialization_url = f"{config.initialization_url}?t={window_tag}"

        browser_args = [
            f"--user-data-dir={config.user_data_dir}",
            f"--remote-debugging-port={config.cdp_port}",
            "--new-window",
            tagged_initialization_url,
            # TODO: These are needed if we don't use CDP but let Playwright manage the browser.
            # "--profile-directory=Profile 1",
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

        async with async_playwright() as playwright:
            max_cdp_connect_attempts = 3
            for attempt in range(max_cdp_connect_attempts):
                try:
                    browser = await playwright.chromium.connect_over_cdp(
                        f"http://localhost:{config.cdp_port}"
                    )
                except Exception:
                    if attempt == max_cdp_connect_attempts - 1:
                        raise
                    await asyncio.sleep(5)
                    continue

            # Grab the browser window ID from the page we just opened.
            page = next(
                p
                for p in browser.contexts[0].pages
                if p.url == tagged_initialization_url
            )
            browser_window_id = await self._wait_for_browser_window_id(page)

        return BrowserWindow(api_key=self._api_key, id=browser_window_id)

    @staticmethod
    async def _wait_for_selector_attached(
        page: Page, selector: str, *, timeout: int
    ) -> ElementHandle | None:
        try:
            return await page.wait_for_selector(
                selector, state="attached", timeout=timeout
            )
        except Exception:
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
            session_id_task,
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
            raise NaradaTimeoutError("Timed out waiting for session ID")

        for task in done:
            if task == session_id_task:
                session_id_elem = task.result()
                if session_id_elem is None:
                    raise NaradaTimeoutError("Timed out waiting for session ID")

                session_id = await session_id_elem.text_content()
                if session_id is None:
                    raise NaradaInitializationError("Session ID is empty")

                return session_id

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


__all__ = [
    "BrowserConfig",
    "Narada",
    "NaradaExtensionMissingError",
    "NaradaInitializationError",
    "BrowserWindow",
    "NaradaTimeoutError",
    "NaradaUnsupportedBrowserError",
]

import asyncio
import logging
import subprocess
import sys
from typing import TypedDict

from playwright.async_api import ElementHandle, Page, async_playwright

from narada.config import BrowserConfig
from narada.errors import (
    NaradaExtensionMissingError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)
from narada.session import NaradaSession
from narada.utils import assert_never

__version__ = "0.1.0"


class _CreateSubprocessExtraArgs(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


class Narada:
    _SESSION_ID_SELECTOR = "#narada-session-id"
    _UNSUPPORTED_BROWSER_INDICATOR_SELECTOR = "#narada-unsupported-browser"
    _EXTENSION_MISSING_INDICATOR_SELECTOR = "#narada-extension-missing"
    _INITIALIZATION_ERROR_INDICATOR_SELECTOR = "#narada-initialization-error"

    async def launch_browser_and_initialize(
        self, config: BrowserConfig | None = None
    ) -> NaradaSession:
        config = config or BrowserConfig()

        browser_args = [
            f"--user-data-dir={config.user_data_dir}",
            f"--remote-debugging-port={config.cdp_port}",
            config.initialization_url,
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

            context = browser.contexts[0]

            # The Chrome extension side panel also creates a page, so we need to find the right page
            # in the main window.
            page = next(p for p in context.pages if p.url == config.initialization_url)

            session_id = await self._wait_for_session_id(page)

            return NaradaSession(id=session_id)

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
    async def _wait_for_session_id(page: Page, *, timeout: int = 15_000) -> str:
        selectors = [
            Narada._SESSION_ID_SELECTOR,
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
    "NaradaSession",
    "NaradaTimeoutError",
    "NaradaUnsupportedBrowserError",
]

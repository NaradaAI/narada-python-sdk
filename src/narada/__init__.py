import asyncio
import subprocess
import sys
from dataclasses import dataclass
from typing import TypedDict

from playwright.async_api import ElementHandle, Page, async_playwright

__version__ = "0.1.0"


class CreateSubprocessExtraArgs(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


@dataclass
class NaradaSession:
    id: str


class Narada:
    _EXTENSION_MISSING_INDICATOR_SELECTOR = "#narada-extension-missing"
    _SESSION_ID_SELECTOR = "#narada-session-id"
    _INITIAL_URL = "https://app.narada.ai/initialize"

    async def launch_browser_and_initialize(self) -> NaradaSession | None:
        # Starting from Chrome 136, the default Chrome data directory can no longer be debugged over
        # CDP:
        # - https://developer.chrome.com/blog/remote-debugging-port
        # - https://github.com/browser-use/browser-use/issues/1520
        user_data_dir = "./narada-user-data-dir"
        cdp_port = 9222

        program = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        args = [
            f"--user-data-dir={user_data_dir}",
            f"--remote-debugging-port={cdp_port}",
            self._INITIAL_URL,
            # TODO: These are needed if we don't use CDP but let Playwright manage the browser.
            # "--profile-directory=Profile 1",
            # "--disable-blink-features=AutomationControlled",
        ]

        # OS-dependent arguments to create the browser process as a detached, independent process.
        extra_args: CreateSubprocessExtraArgs
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
            program,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **extra_args,
        )

        print(f"Browser process started with PID: {browser_process.pid}")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(
                f"http://localhost:{cdp_port}"
            )

            context = browser.contexts[0]

            # The Chrome extension side panel also creates a page, so we need to find the right page
            # in the main window.
            page = next(p for p in context.pages if p.url == self._INITIAL_URL)

            session_id = await self._wait_for_session_id(page)
            if session_id is None:
                return None
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
    async def _wait_for_session_id(page: Page, *, timeout: int = 15_000) -> str | None:
        session_id_task = asyncio.create_task(
            Narada._wait_for_selector_attached(
                page, Narada._SESSION_ID_SELECTOR, timeout=timeout
            )
        )
        extension_missing_indicator_task = asyncio.create_task(
            Narada._wait_for_selector_attached(
                page, Narada._EXTENSION_MISSING_INDICATOR_SELECTOR, timeout=timeout
            )
        )

        done, _ = await asyncio.wait(
            [session_id_task, extension_missing_indicator_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if len(done) == 0:
            return None

        for task in done:
            if task == extension_missing_indicator_task:
                return None

            session_id_elem = task.result()
            if session_id_elem is None:
                return None

            session_id = await session_id_elem.text_content()
            return session_id

        return None


__all__ = ["Narada"]

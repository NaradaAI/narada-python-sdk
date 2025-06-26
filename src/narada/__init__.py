import asyncio
import subprocess
import sys
from typing import TypedDict

from playwright.async_api import async_playwright

__version__ = "0.1.0"


class CreateSubprocessExtraArgs(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


class Narada:
    async def launch_browser(self) -> str:
        # Starting from Chrome 136, the default Chrome data directory can no longer be debugged over
        # CDP:
        # - https://developer.chrome.com/blog/remote-debugging-port
        # - https://github.com/browser-use/browser-use/issues/1520
        user_data_dir = "./narada-user-data-dir"
        cdp_port = 9222
        initial_url = "https://app.narada.ai/initialize"

        program = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        args = [
            f"--user-data-dir={user_data_dir}",
            f"--remote-debugging-port={cdp_port}",
            initial_url,
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
            page = next(
                p for p in context.pages if p.url == "https://app.narada.ai/initialize"
            )

            session_id_elem = page.locator("#narada-session-id")
            await session_id_elem.wait_for(state="attached", timeout=10_000)
            session_id = await session_id_elem.text_content()
            assert session_id is not None

            return session_id


__all__ = ["Narada"]

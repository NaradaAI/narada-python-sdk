from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import aiohttp
from narada_core.errors import (
    NaradaExtensionMissingError,
    NaradaExtensionUnauthenticatedError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)
from narada_core.models import _SdkConfig
from packaging.version import Version
from playwright._impl._errors import Error as PlaywrightError
from playwright.async_api import (
    Browser,
    CDPSession,
    ElementHandle,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api._context_manager import PlaywrightContextManager
from rich.console import Console

from narada.config import BrowserConfig, ProxyConfig
from narada.utils import assert_never, assert_not_none
from narada.version import __version__
from narada.window import (
    CloudBrowserWindow,
    LocalBrowserWindow,
    create_side_panel_url,
)


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

    _auth_headers: dict[str, str]
    _console: Console
    _playwright_context_manager: PlaywrightContextManager | None = None
    _playwright: Playwright | None = None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        auth_headers: dict[str, str] | None = None,
    ) -> None:
        if auth_headers is not None:
            self._auth_headers = auth_headers
        else:
            api_key = api_key or os.environ["NARADA_API_KEY"]
            self._auth_headers = {"x-api-key": api_key}
        self._console = Console()

    async def __aenter__(self) -> Narada:
        await self._validate_sdk_config()

        self._playwright_context_manager = async_playwright()
        self._playwright = await self._playwright_context_manager.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._playwright_context_manager is None:
            return

        await self._playwright_context_manager.__aexit__(*args)
        self._playwright_context_manager = None
        self._playwright = None

    async def _fetch_sdk_config(self) -> _SdkConfig | None:
        base_url = os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2")
        url = f"{base_url}/sdk/config"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._auth_headers) as resp:
                    if not resp.ok:
                        logging.warning(
                            "Failed to fetch SDK config: %s %s",
                            resp.status,
                            await resp.text(),
                        )
                        return None

                    return _SdkConfig.model_validate(await resp.json())
        except Exception as e:
            logging.warning("Failed to fetch SDK config: %s", e)
            return None

    async def _validate_sdk_config(self) -> None:
        config = await self._fetch_sdk_config()
        if config is None:
            return

        package_config = config.packages["narada"]
        current_version = Version(__version__)
        min_required_version = Version(package_config.min_required_version)
        if current_version < min_required_version:
            raise RuntimeError(
                f"narada<={__version__} is not supported. Please upgrade to version "
                f"{package_config.min_required_version} or higher."
            )

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
            auth_headers=self._auth_headers,
            browser_process_id=launch_browser_result.browser_process_id,
            browser_window_id=browser_window_id,
            config=config,
            context=side_panel_page.context,
        )

    async def open_and_initialize_cloud_browser_window(
        self,
        config: BrowserConfig | None = None,
        session_name: str | None = None,
        session_timeout: int | None = None,
    ) -> CloudBrowserWindow:
        """Creates a cloud browser by calling the backend.

        The backend creates a cloud browser session and returns
        a CDP WebSocket URL. This method connects to it, initializes the extension,
        and returns a CloudBrowserWindow instance.
        """
        config = config or BrowserConfig()
        base_url = os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2")
        request_body = {
            "session_name": session_name,
            "session_timeout": session_timeout,
        }
        endpoint_url = f"{base_url}/cloud-browser/create-cloud-browser-session"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint_url,
                headers=self._auth_headers,
                json=request_body,
                timeout=aiohttp.ClientTimeout(
                    total=180
                ),  # 3 minutes for session startup
            ) as resp:
                if not resp.ok:
                    error_text = await resp.text()
                    raise RuntimeError(
                        f"Failed to create cloud browser session: {resp.status} {error_text}\n"
                        f"Endpoint URL: {endpoint_url}"
                    )
                response_data = await resp.json()

        cdp_websocket_url = response_data["cdp_websocket_url"]
        session_id = response_data["session_id"]
        login_url = response_data["login_url"]
        cdp_auth_headers = response_data["cdp_auth_headers"]

        # Connect to browser via CDP with authentication headers and log the user in.
        try:
            return await self._initialize_cloud_browser_window(
                config=config,
                cdp_websocket_url=cdp_websocket_url,
                session_id=session_id,
                login_url=login_url,
                cdp_auth_headers=cdp_auth_headers,
            )
        except Exception:
            # Clean up the session if CDP connection fails
            try:
                async with aiohttp.ClientSession() as cleanup_session:
                    async with cleanup_session.post(
                        f"{base_url}/cloud-browser/stop-cloud-browser-session",
                        headers=self._auth_headers,
                        json={"session_id": session_id, "status": "failed"},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.ok:
                            logging.info(
                                "Cleaned up session %s after CDP connection failure",
                                session_id,
                            )
                        else:
                            logging.warning(
                                "Failed to cleanup session %s: %s",
                                session_id,
                                resp.status,
                            )
            except Exception as cleanup_error:
                logging.warning(
                    "Error cleaning up session %s: %s", session_id, cleanup_error
                )
            # Re-raise the original connection error
            raise

    async def _initialize_cloud_browser_window(
        self,
        *,
        config: BrowserConfig,
        cdp_websocket_url: str,
        session_id: str,
        login_url: str,
        cdp_auth_headers: dict[str, str],
    ) -> CloudBrowserWindow:
        assert self._playwright is not None

        # Connect to browser via CDP with authentication headers
        browser = await self._playwright.chromium.connect_over_cdp(
            cdp_websocket_url, headers=cdp_auth_headers
        )

        # Navigate to login URL (provided by backend with custom token)
        context = browser.contexts[0]
        initialization_page = context.pages[0]
        await initialization_page.goto(
            login_url, wait_until="domcontentloaded", timeout=60_000
        )

        # Wait for browser window ID. The extension can take a bit to be installed, so we retry a
        # few times.
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                browser_window_id = await self._wait_for_browser_window_id(
                    initialization_page, config
                )
            except NaradaExtensionMissingError:
                if attempt == max_attempts - 1:
                    raise
                logging.info("Waiting for Narada extension to be installed...")
                await asyncio.sleep(1)

        # TODO: consider this
        # Get side panel page
        # side_panel_url = create_side_panel_url(config, browser_window_id)
        # side_panel_page = next(
        #     (p for p in context.pages if p.url == side_panel_url), None
        # )
        # await self._fix_download_behavior(side_panel_page)

        cloud_window = CloudBrowserWindow(
            browser_window_id=browser_window_id,
            session_id=session_id,
            auth_headers=self._auth_headers,
        )

        if config.interactive:
            self._print_success_message(browser_window_id)

        return cloud_window

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

        if config.proxy is not None:
            raise ValueError(
                "Proxy configuration is not supported for `initialize_in_existing_browser_window`. "
                "Proxy settings must be specified when launching Chrome. "
                "Use `open_and_initialize_browser_window` instead."
            )

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
            auth_headers=self._auth_headers,
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

        # When proxy auth is needed, launch with about:blank to avoid Chrome's startup auth prompt.
        # We'll set up the CDP auth handler and then navigate to the init URL.
        proxy_requires_auth = (
            config.proxy is not None and config.proxy.requires_authentication
        )
        launch_url = "about:blank" if proxy_requires_auth else tagged_initialization_url

        browser_args = [
            f"--user-data-dir={config.user_data_dir}",
            f"--profile-directory={config.profile_directory}",
            f"--remote-debugging-port={config.cdp_port}",
            "--no-default-browser-check",
            "--no-first-run",
            "--new-window",
            launch_url,
        ]

        # Add proxy arguments if configured.
        if config.proxy is not None:
            config.proxy.validate()
            browser_args.append(f"--proxy-server={config.proxy.server}")

            if config.proxy.bypass:
                browser_args.append(f"--proxy-bypass-list={config.proxy.bypass}")

            if config.proxy.ignore_cert_errors:
                browser_args.append("--ignore-certificate-errors")

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

        # Track whether we've already navigated from about:blank to the initialization URL.
        # This is only relevant when proxy auth is enabled, where we launch with about:blank
        # to set up CDP auth handlers before any network traffic. We must only navigate once,
        # because on retry iterations context.pages[0] could be any page (side panel, devtools,
        # etc.) and navigating it would break the initialization flow.
        did_initial_navigation = False

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

            context = browser.contexts[0]

            # If proxy auth is needed, set up the handler at browser level then navigate to the
            # initialization page. After navigation succeeds, Chrome has cached the proxy
            # credentials, so we can detach the CDP session.
            if proxy_requires_auth and not did_initial_navigation:
                proxy_cdp_session = (
                    await self._setup_proxy_authentication_browser_level(
                        browser,
                        # Not None because `proxy_requires_auth` is True.
                        assert_not_none(config.proxy),
                    )
                )
                blank_page = context.pages[0]
                await blank_page.goto(tagged_initialization_url)
                await proxy_cdp_session.detach()
                did_initial_navigation = True

            # Grab the browser window ID from the page we just opened.
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
    async def _wait_for_browser_window_id_silently(page: Page, *, timeout: int) -> str:
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
        self, page: Page, *, per_attempt_timeout: int
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
        timeout: int = 30_000,
    ) -> str:
        """Waits for the browser window ID to be available, potentially letting the user respond to
        recoverable errors interactively.
        """
        if config.interactive:
            return await self._wait_for_browser_window_id_interactively(
                initialization_page, per_attempt_timeout=timeout
            )
        else:
            return await Narada._wait_for_browser_window_id_silently(
                initialization_page, timeout=timeout
            )

    async def _setup_proxy_authentication_browser_level(
        self, browser: Browser, proxy_config: ProxyConfig
    ) -> CDPSession:
        """Sets up proxy authentication handling via CDP at the browser level.

        This uses a browser-level CDP session which can intercept auth challenges before they reach
        individual pages, preventing Chrome from showing the proxy authentication dialog.

        Chrome caches proxy credentials for the session after the first successful authentication.
        The caller should detach the returned CDP session after the first navigation succeeds.
        """
        cdp_session = await browser.new_browser_cdp_session()

        # Enable Fetch domain with a catch-all pattern to intercept auth challenges.
        await cdp_session.send(
            "Fetch.enable",
            {
                "handleAuthRequests": True,
                "patterns": [{"urlPattern": "*"}],
            },
        )

        async def handle_auth(params: dict[str, Any]) -> None:
            request_id = params.get("requestId")
            auth_challenge = params.get("authChallenge", {})

            # Only handle proxy auth challenges
            if auth_challenge.get("source") != "Proxy":
                return

            try:
                await cdp_session.send(
                    "Fetch.continueWithAuth",
                    {
                        "requestId": request_id,
                        "authChallengeResponse": {
                            "response": "ProvideCredentials",
                            "username": proxy_config.username,
                            "password": proxy_config.password,
                        },
                    },
                )
                logging.debug("Browser-level proxy authentication credentials provided")
            except Exception as e:
                logging.error("Failed to respond to proxy auth challenge: %s", e)

        async def handle_request_paused(params: dict[str, Any]) -> None:
            # Continue all paused requests immediately
            request_id = params.get("requestId")
            try:
                await cdp_session.send(
                    "Fetch.continueRequest", {"requestId": request_id}
                )
            except Exception:
                pass

        cdp_session.on(
            "Fetch.authRequired",
            lambda params: asyncio.create_task(handle_auth(params)),
        )
        cdp_session.on(
            "Fetch.requestPaused",
            lambda params: asyncio.create_task(handle_request_paused(params)),
        )

        return cdp_session

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

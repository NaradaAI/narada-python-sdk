import asyncio
import logging
import os
import subprocess
import time
from abc import ABC
from http import HTTPStatus
from pathlib import Path
from typing import IO, Any, Optional, TypeVar, overload

import aiohttp
from narada.config import BrowserConfig
from narada_core.actions.models import (
    ActionTraceItem,
    AgenticMouseAction,
    AgenticMouseActionRequest,
    AgenticSelectorAction,
    AgenticSelectorRequest,
    AgenticSelectorResponse,
    AgenticSelectors,
    AgentResponse,
    AgentUsage,
    CloseWindowRequest,
    ExtensionActionRequest,
    ExtensionActionResponse,
    GetFullHtmlRequest,
    GetFullHtmlResponse,
    GetScreenshotRequest,
    GetScreenshotResponse,
    GetSimplifiedHtmlRequest,
    GetSimplifiedHtmlResponse,
    GoToUrlRequest,
    PrintMessageRequest,
    ReadGoogleSheetRequest,
    ReadGoogleSheetResponse,
    RecordedClick,
    WriteGoogleSheetRequest,
)
from narada_core.errors import (
    NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE,
    NaradaError,
    NaradaTimeoutError,
)
from narada_core.models import (
    Agent,
    File,
    RemoteDispatchChatHistoryItem,
    Response,
    UserResourceCredentials,
)
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_StructuredOutput = TypeVar("_StructuredOutput", bound=BaseModel)


_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


class _PresignedPost(BaseModel):
    url: str
    fields: dict[str, Any]


class BaseBrowserWindow(ABC):
    _api_key: str
    _base_url: str
    _browser_window_id: str

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        browser_window_id: str,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._browser_window_id = browser_window_id

    @property
    def browser_window_id(self) -> str:
        return self._browser_window_id

    async def upload_file(self, *, file: IO) -> File:
        """Uploads a file that can be used as an attachment in a subsequent `agent` request.

        The file is temporarily saved in Narada cloud and expires after 1 day. It can only be
        accessed by the user who uploaded it.
        """
        # Get the base filename without directories.
        filename = Path(file.name).name

        async with aiohttp.ClientSession() as session:
            # First generate a presigned POST for uploading the file.
            async with session.post(
                f"{self._base_url}/remote-dispatch/generate-file-upload-presigned-post",
                headers={"x-api-key": self._api_key},
                json={"filename": filename},
            ) as resp:
                resp.raise_for_status()
                resp_json = await resp.json()

            presigned_post = _PresignedPost.model_validate(resp_json)
            object_key: str = presigned_post.fields["key"]

            # Upload the file with a POST request where:
            # - The URL is the presigned POST URL.
            # - The form fields are the presigned POST fields.
            # - The form data has an addition 'file' field that contains the file contents.
            form_data = aiohttp.FormData(presigned_post.fields)
            form_data.add_field("file", file)
            async with session.post(presigned_post.url, data=form_data) as resp:
                resp.raise_for_status()

        return File(key=object_key)

    @overload
    async def dispatch_request(
        self,
        *,
        prompt: str,
        agent: Agent | str = Agent.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: None = None,
        previous_request_id: str | None = None,
        chat_history: list[RemoteDispatchChatHistoryItem] | None = None,
        additional_context: dict[str, str] | None = None,
        attachment: File | None = None,
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        variables: dict[str, str] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, Any] | None = None,
        timeout: int = 1000,
    ) -> Response[None]: ...

    @overload
    async def dispatch_request(
        self,
        *,
        prompt: str,
        agent: Agent | str = Agent.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: type[_StructuredOutput],
        previous_request_id: str | None = None,
        chat_history: list[RemoteDispatchChatHistoryItem] | None = None,
        additional_context: dict[str, str] | None = None,
        attachment: File | None = None,
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        variables: dict[str, str] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, Any] | None = None,
        timeout: int = 1000,
    ) -> Response[_StructuredOutput]: ...

    async def dispatch_request(
        self,
        *,
        prompt: str,
        agent: Agent | str = Agent.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: type[BaseModel] | None = None,
        previous_request_id: str | None = None,
        chat_history: list[RemoteDispatchChatHistoryItem] | None = None,
        additional_context: dict[str, str] | None = None,
        attachment: File | None = None,
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        variables: dict[str, str] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, Any] | None = None,
        timeout: int = 1000,
    ) -> Response:
        """Low-level API for invoking an agent in the Narada extension side panel chat.

        The higher-level `agent` method should be preferred for most use cases.
        """
        deadline = time.monotonic() + timeout

        headers = {"x-api-key": self._api_key}

        agent_prefix = (
            agent.prompt_prefix() if isinstance(agent, Agent) else f"{agent} "
        )
        body: dict[str, Any] = {
            "prompt": agent_prefix + prompt,
            "browserWindowId": self.browser_window_id,
            "timeZone": time_zone,
        }
        if clear_chat is not None:
            body["clearChat"] = clear_chat
        if generate_gif is not None:
            body["saveScreenshots"] = generate_gif
        if output_schema is not None:
            body["responseFormat"] = {
                "type": "jsonSchema",
                "jsonSchema": output_schema.model_json_schema(),
            }
        if previous_request_id is not None:
            body["previousRequestId"] = previous_request_id
        if chat_history is not None:
            body["chatHistory"] = chat_history
        if additional_context is not None:
            body["additionalContext"] = additional_context
        if attachment is not None:
            body["attachment"] = attachment
        if user_resource_credentials is not None:
            body["userResourceCredentials"] = user_resource_credentials
        if variables is not None:
            body["variables"] = variables
        if callback_url is not None:
            body["callbackUrl"] = callback_url
        if callback_secret is not None:
            body["callbackSecret"] = callback_secret
        if callback_headers is not None:
            body["callbackHeaders"] = callback_headers

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/remote-dispatch",
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    resp.raise_for_status()
                    request_id = (await resp.json())["requestId"]

                while (now := time.monotonic()) < deadline:
                    async with session.get(
                        f"{self._base_url}/remote-dispatch/responses/{request_id}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=deadline - now),
                    ) as resp:
                        resp.raise_for_status()
                        response = await resp.json()

                    response["requestId"] = request_id

                    if response["status"] != "pending":
                        response_content = response["response"]
                        if response_content is not None:
                            # Populate the `structuredOutput` field. This is a client-side field
                            # that's not directly returned by the API.
                            if output_schema is None:
                                response_content["structuredOutput"] = None
                            else:
                                structured_output = output_schema.model_validate_json(
                                    response_content["text"]
                                )
                                response_content["structuredOutput"] = structured_output

                        return response

                    # Poll every 3 seconds.
                    await asyncio.sleep(3)
                else:
                    raise NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(timeout)

        except asyncio.TimeoutError:
            raise NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(timeout)

    @overload
    async def agent(
        self,
        *,
        prompt: str,
        agent: Agent | str = Agent.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: None = None,
        attachment: File | None = None,
        time_zone: str = "America/Los_Angeles",
        variables: dict[str, str] | None = None,
        timeout: int = 1000,
    ) -> AgentResponse[None]: ...

    @overload
    async def agent(
        self,
        *,
        prompt: str,
        agent: Agent | str = Agent.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: type[_StructuredOutput],
        attachment: File | None = None,
        time_zone: str = "America/Los_Angeles",
        variables: dict[str, str] | None = None,
        timeout: int = 1000,
    ) -> AgentResponse[_StructuredOutput]: ...

    async def agent(
        self,
        *,
        prompt: str,
        agent: Agent | str = Agent.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: type[BaseModel] | None = None,
        attachment: File | None = None,
        time_zone: str = "America/Los_Angeles",
        variables: dict[str, str] | None = None,
        timeout: int = 1000,
    ) -> AgentResponse:
        """Invokes an agent in the Narada extension side panel chat."""
        remote_dispatch_response = await self.dispatch_request(
            prompt=prompt,
            agent=agent,
            clear_chat=clear_chat,
            generate_gif=generate_gif,
            output_schema=output_schema,
            attachment=attachment,
            time_zone=time_zone,
            variables=variables,
            timeout=timeout,
        )
        response_content = remote_dispatch_response["response"]
        assert response_content is not None

        action_trace_raw = response_content.get("actionTrace")
        action_trace = (
            [ActionTraceItem.model_validate(item) for item in action_trace_raw]
            if action_trace_raw is not None
            else None
        )

        return AgentResponse(
            request_id=remote_dispatch_response["requestId"],
            status=remote_dispatch_response["status"],
            text=response_content["text"],
            structured_output=response_content.get("structuredOutput"),
            usage=AgentUsage.model_validate(remote_dispatch_response["usage"]),
            action_trace=action_trace,
        )

    async def agentic_selector(
        self,
        *,
        action: AgenticSelectorAction,
        selectors: AgenticSelectors,
        fallback_operator_query: str,
        # Larger default timeout because Operator can take a bit to run.
        timeout: int | None = 60,
    ) -> AgenticSelectorResponse:
        """Performs an action on an element specified by the given selectors, falling back to using
        the Operator agent if the selectors fail to match a unique element.
        """
        response_model = (
            AgenticSelectorResponse
            if action["type"] in {"get_text", "get_property"}
            else None
        )
        result = await self._run_extension_action(
            AgenticSelectorRequest(
                action=action,
                selectors=selectors,
                response_model=response_model,
                fallback_operator_query=fallback_operator_query,
            ),
            timeout=timeout,
        )

        if result is None:
            return {"value": None}

        return result

    async def agentic_mouse_action(
        self,
        *,
        action: AgenticMouseAction,
        recorded_click: RecordedClick,
        fallback_operator_query: str,
        resize_window: bool = True,
        timeout: int | None = 60,
    ) -> None:
        """Performs a mouse action at the specified click coordinates, falling back to using
        the Operator agent if the click fails.
        """
        return await self._run_extension_action(
            AgenticMouseActionRequest(
                action=action,
                recorded_click=recorded_click,
                resize_window=resize_window,
                fallback_operator_query=fallback_operator_query,
            ),
            timeout=timeout,
        )

    async def close(self, *, timeout: int | None = None) -> None:
        """Gracefully closes the current browser window."""
        return await self._run_extension_action(CloseWindowRequest(), timeout=timeout)

    async def go_to_url(
        self, *, url: str, new_tab: bool = False, timeout: int | None = None
    ) -> None:
        """Navigates the active page in this window to the given URL."""
        return await self._run_extension_action(
            GoToUrlRequest(url=url, new_tab=new_tab), timeout=timeout
        )

    async def print_message(self, *, message: str, timeout: int | None = None) -> None:
        """Prints a message in the Narada extension side panel chat."""
        return await self._run_extension_action(
            PrintMessageRequest(message=message), timeout=timeout
        )

    async def read_google_sheet(
        self,
        *,
        spreadsheet_id: str,
        range: str,
        timeout: int | None = None,
    ) -> ReadGoogleSheetResponse:
        """Reads a range of cells from a Google Sheet."""
        return await self._run_extension_action(
            ReadGoogleSheetRequest(spreadsheet_id=spreadsheet_id, range=range),
            ReadGoogleSheetResponse,
            timeout=timeout,
        )

    async def write_google_sheet(
        self,
        *,
        spreadsheet_id: str,
        range: str,
        values: list[list[str]],
        timeout: int | None = None,
    ) -> None:
        """Writes a range of cells to a Google Sheet."""
        return await self._run_extension_action(
            WriteGoogleSheetRequest(
                spreadsheet_id=spreadsheet_id, range=range, values=values
            ),
            timeout=timeout,
        )

    async def get_full_html(self, *, timeout: int | None = None) -> GetFullHtmlResponse:
        """Gets the full HTML content of the current page."""
        return await self._run_extension_action(
            GetFullHtmlRequest(),
            GetFullHtmlResponse,
            timeout=timeout,
        )

    async def get_simplified_html(
        self, *, timeout: int | None = None
    ) -> GetSimplifiedHtmlResponse:
        """Gets the simplified HTML content of the current page."""
        return await self._run_extension_action(
            GetSimplifiedHtmlRequest(),
            GetSimplifiedHtmlResponse,
            timeout=timeout,
        )

    async def get_screenshot(
        self, *, timeout: int | None = None
    ) -> GetScreenshotResponse:
        """Takes a screenshot of the current browser window."""
        return await self._run_extension_action(
            GetScreenshotRequest(),
            GetScreenshotResponse,
            timeout=timeout,
        )

    @overload
    async def _run_extension_action(
        self,
        request: ExtensionActionRequest,
        response_model: None = None,
        *,
        timeout: int | None = None,
    ) -> None: ...

    @overload
    async def _run_extension_action(
        self,
        request: ExtensionActionRequest,
        response_model: type[_ResponseModel],
        *,
        timeout: int | None = None,
    ) -> _ResponseModel: ...

    async def _run_extension_action(
        self,
        request: ExtensionActionRequest,
        response_model: type[_ResponseModel] | None = None,
        *,
        timeout: int | None = None,
    ) -> _ResponseModel | None:
        headers = {"x-api-key": self._api_key}

        body = {
            "action": request.model_dump(),
            "browserWindowId": self.browser_window_id,
        }
        if timeout is not None:
            body["timeout"] = timeout

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base_url}/extension-actions",
                headers=headers,
                json=body,
                # Don't specify `timeout` here as the (soft) timeout is handled by the server.
            ) as resp:
                if resp.status == HTTPStatus.GATEWAY_TIMEOUT:
                    raise NaradaTimeoutError
                resp.raise_for_status()
                resp_json = await resp.json()

        response = ExtensionActionResponse.model_validate(resp_json)
        if response.status == "error":
            raise NaradaError(response.error)

        if response_model is None:
            return None

        assert response.data is not None
        return response_model.model_validate_json(response.data)


class LocalBrowserWindow(BaseBrowserWindow):
    _browser_process_id: int | None
    _config: BrowserConfig
    _context: BrowserContext

    def __init__(
        self,
        *,
        api_key: str,
        browser_process_id: int | None,
        browser_window_id: str,
        config: BrowserConfig,
        context: BrowserContext,
    ) -> None:
        base_url = os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2")
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            browser_window_id=browser_window_id,
        )
        self._browser_process_id = browser_process_id
        self._config = config
        self._context = context

    @property
    def browser_process_id(self) -> int | None:
        return self._browser_process_id

    def __str__(self) -> str:
        return (
            "LocalBrowserWindow("
            f"browser_process_id={self._browser_process_id}, "
            f"browser_window_id={self.browser_window_id}"
            ")"
        )

    async def reinitialize(self) -> None:
        side_panel_url = create_side_panel_url(self._config, self._browser_window_id)
        side_panel_page = next(
            p for p in self._context.pages if p.url == side_panel_url
        )

        # Refresh the extension side panel, which ensures any inflight Narada operations are
        # canceled.
        await side_panel_page.reload()


class RemoteBrowserWindow(BaseBrowserWindow):
    def __init__(self, *, browser_window_id: str, api_key: str | None = None) -> None:
        base_url = os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2")
        super().__init__(
            api_key=api_key or os.environ["NARADA_API_KEY"],
            base_url=base_url,
            browser_window_id=browser_window_id,
        )

    def __str__(self) -> str:
        return f"RemoteBrowserWindow(browser_window_id={self.browser_window_id})"


class ManagedBrowserWindow(BaseBrowserWindow):
    """A browser window that connects to a backend-managed containerized browser via CDP.

    This class connects to a browser container created by the backend API and provides
    the same interface as other browser window classes for agent operations.
    """

    _cdp_websocket_url: str
    _session_id: str
    _run_locally: bool
    _playwright: Playwright | None
    _browser: Browser | None
    _context: BrowserContext | None
    _page: Page | None

    def __init__(
        self,
        *,
        browser_window_id: str,
        cdp_websocket_url: str,
        session_id: str,
        run_locally: bool = False,
        api_key: str | None = None,
    ) -> None:
        base_url = os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2")
        super().__init__(
            api_key=api_key or os.environ["NARADA_API_KEY"],
            base_url=base_url,
            browser_window_id=browser_window_id,
        )
        self._cdp_websocket_url = cdp_websocket_url
        self._session_id = session_id
        self._run_locally = run_locally
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def browser(self) -> Browser | None:
        """Get the Playwright browser instance."""
        return self._browser

    @property
    def context(self) -> BrowserContext | None:
        """Get the Playwright browser context."""
        return self._context

    @property
    def page(self) -> Page | None:
        """Get the default Playwright page."""
        return self._page

    @property
    def session_id(self) -> str:
        """Get the session ID (container ID)."""
        return self._session_id

    async def connect(self) -> None:
        """Connect to the browser via CDP."""
        if self._browser is not None:
            return  # Already connected

        # Connect via Playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(
            self._cdp_websocket_url
        )

        # Get or create context
        if self._browser.contexts:
            self._context = self._browser.contexts[0]
        else:
            self._context = await self._browser.new_context()

        # Get or create page
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        # Wait for extensions to initialize
        await asyncio.sleep(3)

    async def cleanup(self) -> None:
        """Clean up Playwright resources and stop the backend container/task."""
        # Stop the backend container/task first
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/managed-browser/stop-managed-browser-session",
                    headers={"x-api-key": self._api_key},
                    json={
                        "container_id": self._session_id,
                        "run_locally": self._run_locally,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.ok:
                        response_data = await resp.json()
                        if not response_data.get("success"):
                            logger.warning(
                                f"Failed to stop session: {response_data.get('message')}"
                            )
                    else:
                        logger.warning(f"Failed to stop session: {resp.status}")
        except Exception as e:
            logger.warning(f"Error calling stop session endpoint: {e}")

        # Then clean up Playwright resources
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def __aenter__(self) -> "ManagedBrowserWindow":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.cleanup()

    def __str__(self) -> str:
        return (
            f"ManagedBrowserWindow("
            f"session_id={self._session_id}, "
            f"browser_window_id={self.browser_window_id})"
        )


def create_side_panel_url(config: BrowserConfig, browser_window_id: str) -> str:
    return f"chrome-extension://{config.extension_id}/sidepanel.html?browserWindowId={browser_window_id}"

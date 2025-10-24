import asyncio
import os
import time
from abc import ABC
from http import HTTPStatus
from pathlib import Path
from typing import IO, Any, TypeVar, overload

import aiohttp
from narada_core.actions.models import (
    AgenticSelectorAction,
    AgenticSelectorRequest,
    AgenticSelectors,
    AgentResponse,
    AgentUsage,
    CloseWindowRequest,
    ExtensionActionRequest,
    ExtensionActionResponse,
    GoToUrlRequest,
    PrintMessageRequest,
    ReadGoogleSheetRequest,
    ReadGoogleSheetResponse,
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
from playwright.async_api import BrowserContext
from pydantic import BaseModel

from narada.config import BrowserConfig

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

        return AgentResponse(
            status=remote_dispatch_response["status"],
            text=response_content["text"],
            structured_output=response_content.get("structuredOutput"),
            usage=AgentUsage.model_validate(remote_dispatch_response["usage"]),
        )

    async def agentic_selector(
        self,
        *,
        action: AgenticSelectorAction,
        selectors: AgenticSelectors,
        fallback_operator_query: str,
        # Larger default timeout because Operator can take a bit to run.
        timeout: int | None = 60,
    ) -> None:
        """Performs an action on an element specified by the given selectors, falling back to using
        the Operator agent if the selectors fail to match a unique element.
        """
        return await self._run_extension_action(
            AgenticSelectorRequest(
                action=action,
                selectors=selectors,
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
        super().__init__(
            api_key=api_key,
            base_url=os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2"),
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
        super().__init__(
            api_key=api_key or os.environ["NARADA_API_KEY"],
            base_url=os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2"),
            browser_window_id=browser_window_id,
        )

    def __str__(self) -> str:
        return f"RemoteBrowserWindow(browser_window_id={self.browser_window_id})"


def create_side_panel_url(config: BrowserConfig, browser_window_id: str) -> str:
    return f"chrome-extension://{config.extension_id}/sidepanel.html?browserWindowId={browser_window_id}"

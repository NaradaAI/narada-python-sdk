import abc
import asyncio
import os
import time
from http import HTTPStatus
from typing import Any, Generic, Literal, TypedDict, TypeVar, overload

import aiohttp
from playwright.async_api import BrowserContext
from pydantic import BaseModel

from narada.actions.models import (
    AgentResponse,
    ExtensionActionRequest,
    GoToUrlRequest,
    GoToUrlResponse,
    PrintMessageRequest,
    PrintMessageResponse,
)
from narada.config import BrowserConfig
from narada.errors import NaradaTimeoutError
from narada.models import Agent, RemoteDispatchChatHistoryItem, UserResourceCredentials

_StructuredOutput = TypeVar("_StructuredOutput", bound=BaseModel)

_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class ResponseContent(TypedDict, Generic[_MaybeStructuredOutput]):
    text: str
    structuredOutput: _MaybeStructuredOutput


class Response(TypedDict, Generic[_MaybeStructuredOutput]):
    requestId: str
    status: Literal["success", "error"]
    response: ResponseContent[_MaybeStructuredOutput] | None
    createdAt: str
    completedAt: str | None


_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


class BaseBrowserWindow(abc.ABC):
    api_key: str
    _browser_window_id: str

    def __init__(self, *, api_key: str, browser_window_id: str) -> None:
        self.api_key = api_key
        self._browser_window_id = browser_window_id

    @property
    def browser_window_id(self) -> str:
        return self._browser_window_id

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
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        timeout: int = 120,
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
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        timeout: int = 120,
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
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        timeout: int = 120,
    ) -> Response:
        deadline = time.monotonic() + timeout

        headers = {"x-api-key": self.api_key}

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
        if user_resource_credentials is not None:
            body["userResourceCredentials"] = user_resource_credentials
        if callback_url is not None:
            body["callbackUrl"] = callback_url
        if callback_secret is not None:
            body["callbackSecret"] = callback_secret

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.narada.ai/fast/v2/remote-dispatch",
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    resp.raise_for_status()
                    request_id = (await resp.json())["requestId"]

                while (now := time.monotonic()) < deadline:
                    async with session.get(
                        f"https://api.narada.ai/fast/v2/remote-dispatch/responses/{request_id}",
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
                    raise NaradaTimeoutError

        except asyncio.TimeoutError:
            raise NaradaTimeoutError

    @overload
    async def agent(
        self,
        *,
        prompt: str,
        agent: Agent | str = Agent.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: None = None,
        time_zone: str = "America/Los_Angeles",
        timeout: int = 120,
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
        time_zone: str = "America/Los_Angeles",
        timeout: int = 120,
    ) -> AgentResponse[_StructuredOutput]: ...

    async def agent(
        self,
        *,
        prompt: str,
        agent: Agent | str = Agent.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: type[BaseModel] | None = None,
        time_zone: str = "America/Los_Angeles",
        timeout: int = 120,
    ) -> AgentResponse:
        remote_dispatch_response = await self.dispatch_request(
            prompt=prompt,
            agent=agent,
            clear_chat=clear_chat,
            generate_gif=generate_gif,
            output_schema=output_schema,
            time_zone=time_zone,
            timeout=timeout,
        )
        response_content = remote_dispatch_response["response"]
        assert response_content is not None

        return AgentResponse(
            status=remote_dispatch_response["status"],
            text=response_content["text"],
            structured_output=response_content.get("structuredOutput"),
        )

    async def go_to_url(
        self, *, url: str, timeout: int | None = None
    ) -> GoToUrlResponse:
        return await self._run_extension_action(
            GoToUrlRequest(url=url), GoToUrlResponse, timeout=timeout
        )

    async def print_message(
        self, *, message: str, timeout: int | None = None
    ) -> PrintMessageResponse:
        return await self._run_extension_action(
            PrintMessageRequest(message=message),
            PrintMessageResponse,
            timeout=timeout,
        )

    async def _run_extension_action(
        self,
        request: ExtensionActionRequest,
        response_model: type[_ResponseModel],
        *,
        timeout: int | None = None,
    ) -> _ResponseModel:
        headers = {"x-api-key": self.api_key}

        body = {
            "action": request.model_dump(),
            "browserWindowId": self.browser_window_id,
        }
        if timeout is not None:
            body["timeout"] = timeout

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.narada.ai/fast/v2/extension-actions",
                headers=headers,
                json=body,
                # Don't specify `timeout` here as the (soft) timeout is handled by the server.
            ) as resp:
                if resp.status == HTTPStatus.GATEWAY_TIMEOUT:
                    raise NaradaTimeoutError
                resp.raise_for_status()

                return response_model.model_validate(await resp.json())


class LocalBrowserWindow(BaseBrowserWindow):
    _config: BrowserConfig
    _context: BrowserContext

    def __init__(
        self,
        *,
        api_key: str,
        browser_window_id: str,
        config: BrowserConfig,
        context: BrowserContext,
    ) -> None:
        super().__init__(api_key=api_key, browser_window_id=browser_window_id)
        self._config = config
        self._context = context

    def __str__(self) -> str:
        return f"LocalBrowserWindow(browser_window_id={self.browser_window_id})"

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
        api_key = api_key or os.environ["NARADA_API_KEY"]
        super().__init__(api_key=api_key, browser_window_id=browser_window_id)

    def __str__(self) -> str:
        return f"RemoteBrowserWindow(browser_window_id={self.browser_window_id})"


def create_side_panel_url(config: BrowserConfig, browser_window_id: str) -> str:
    return f"chrome-extension://{config.extension_id}/sidepanel.html?browserWindowId={browser_window_id}"

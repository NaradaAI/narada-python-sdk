import abc
import asyncio
import json
import os
import time
from typing import Any, Generic, Literal, TypedDict, TypeVar, overload

from js import AbortController, setTimeout  # type: ignore
from pydantic import BaseModel
from pyodide.ffi import create_once_callable
from pyodide.http import pyfetch

from narada.errors import NaradaTimeoutError
from narada.models import (
    Agent,
    RemoteDispatchChatHistoryItem,
    UserResourceCredentials,
)

_StructuredOutput = TypeVar("_StructuredOutput", bound=BaseModel)

_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class User(BaseModel):
    uid: str
    token: str
    env: Literal['prod', 'dev']


class ResponseContent(TypedDict, Generic[_MaybeStructuredOutput]):
    text: str
    structuredOutput: _MaybeStructuredOutput


class Response(TypedDict, Generic[_MaybeStructuredOutput]):
    requestId: str
    status: Literal["success", "error"]
    response: ResponseContent[_MaybeStructuredOutput] | None
    createdAt: str
    completedAt: str | None


class BaseBrowserWindow(abc.ABC):
    api_key: str | None
    user: User | None
    _browser_window_id: str

    def __init__(self, *, api_key: str | None, user: User | None, browser_window_id: str) -> None:
        self.api_key = api_key
        self.user = user
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

        headers = {"Content-Type": "application/json"}
        base_url = "http://localhost:8000/fast/v2" if self.user.get(
            "env") == "dev" else "https://api.narada.ai/fast/v2"

        if self.user is not None:
            headers["Authorization"] = f"Bearer {self.user.get('token')}"
            headers["X-Narada-User-ID"] = self.user.get("uid")
            headers['X-Narada-Env'] = self.user.get('env')
        elif self.api_key is not None:
            headers["x-api-key"] = self.api_key
        else:
            raise ValueError("Either api_key or user must be provided")

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
            controller = AbortController.new()
            signal = controller.signal

            setTimeout(create_once_callable(controller.abort), timeout * 1000)
            fetch_response = await pyfetch(
                f"{base_url}/remote-dispatch",
                method="POST",
                headers=headers,
                body=json.dumps(body),
                signal=signal,
            )

            if not fetch_response.ok:
                status = fetch_response.status
                text = await fetch_response.text()
                raise RuntimeError(f"Failed to dispatch request: {status} {text}")

            request_id = (await fetch_response.json())["requestId"]

            while (now := time.monotonic()) < deadline:
                abort_controller = AbortController.new()
                signal = abort_controller.signal

                setTimeout(
                    create_once_callable(abort_controller.abort),
                    (deadline - now) * 1000,
                )
                fetch_response = await pyfetch(
                    f"{base_url}/remote-dispatch/responses/{request_id}",
                    headers=headers,
                    signal=signal,
                )

                if not fetch_response.ok:
                    status = fetch_response.status
                    text = await fetch_response.text()
                    raise RuntimeError(f"Failed to poll for response: {status} {text}")

                response = await fetch_response.json()

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


class RemoteBrowserWindow(BaseBrowserWindow):
    def __init__(self, *, browser_window_id: str, api_key: str | None = None, user: User | None = None) -> None:
        api_key = api_key or os.environ.get("NARADA_API_KEY")
        super().__init__(api_key=api_key, user=user, browser_window_id=browser_window_id)

    def __str__(self) -> str:
        return f"RemoteBrowserWindow(browser_window_id={self.browser_window_id}, user={self.user})"

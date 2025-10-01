import asyncio
import json
import os
import time
from abc import ABC
from http import HTTPStatus
from typing import IO, TYPE_CHECKING, Any, Literal, TypeVar, overload

from js import AbortController, setTimeout  # type: ignore
from narada_core.actions.models import (
    AgenticSelectorAction,
    AgenticSelectorRequest,
    AgenticSelectors,
    AgentResponse,
    AgentUsage,
    ExtensionActionRequest,
    ExtensionActionResponse,
    GoToUrlRequest,
    PrintMessageRequest,
    ReadGoogleSheetRequest,
    ReadGoogleSheetResponse,
    WriteGoogleSheetRequest,
)
from narada_core.errors import NaradaError, NaradaTimeoutError
from narada_core.models import (
    Agent,
    File,
    RemoteDispatchChatHistoryItem,
    Response,
    UserResourceCredentials,
)
from pydantic import BaseModel
from pyodide.ffi import create_once_callable
from pyodide.http import pyfetch

# Magic variable injected by the JavaScript harness that stores the IDs of the current runnables
# in the stack on the frontend.
# TODO: `.get()` won't be necessary once frontend is fully migrated.
_narada_parent_run_ids: list[str] = globals().get("_narada_parent_run_ids", [])

if TYPE_CHECKING:
    # Magic function injected by the JavaScript harness to get the current user's ID token.
    async def _narada_get_id_token() -> str: ...


_StructuredOutput = TypeVar("_StructuredOutput", bound=BaseModel)

_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


class BaseBrowserWindow(ABC):
    _api_key: str | None
    _base_url: str
    _user_id: str | None
    _env: Literal["prod", "dev", None]
    _browser_window_id: str

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        user_id: str | None,
        env: Literal["prod", "dev", None] = "prod",
        browser_window_id: str,
    ) -> None:
        if api_key is None and (user_id is None or env is None):
            raise ValueError(
                "Either `api_key` or all of `user_id`, `user_id_token`, and `env` must be provided"
            )

        self._api_key = api_key
        self._base_url = base_url
        self._user_id = user_id
        self._env = env
        self._browser_window_id = browser_window_id

    @property
    def browser_window_id(self) -> str:
        return self._browser_window_id

    async def upload_file(self, *, file: IO) -> File:
        """Uploads a file that can be used as an attachment in a subsequent `agent` request.

        The file is temporarily saved in Narada cloud and expires after 1 day. It can only be
        accessed by the user who uploaded it.
        """
        raise NotImplementedError(
            "Uploading files is not supported in the browser environment"
        )

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
        variables: dict[str, str] | None = None,
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
        variables: dict[str, str] | None = None,
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
        variables: dict[str, str] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        timeout: int = 120,
    ) -> Response:
        """Low-level API for invoking an agent in the Narada extension side panel chat.

        The higher-level `agent` method should be preferred for most use cases.
        """
        deadline = time.monotonic() + timeout

        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["x-api-key"] = self._api_key
        else:
            assert self._user_id is not None
            assert self._env is not None

            headers["Authorization"] = f"Bearer {await _narada_get_id_token()}"
            headers["X-Narada-User-ID"] = self._user_id
            headers["X-Narada-Env"] = self._env

        agent_prefix = (
            agent.prompt_prefix() if isinstance(agent, Agent) else f"{agent} "
        )
        body: dict[str, Any] = {
            "prompt": agent_prefix + prompt,
            "browserWindowId": self.browser_window_id,
            "timeZone": time_zone,
            "parentRunIds": _narada_parent_run_ids,
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
        if variables is not None:
            body["variables"] = variables
        if callback_url is not None:
            body["callbackUrl"] = callback_url
        if callback_secret is not None:
            body["callbackSecret"] = callback_secret

        try:
            controller = AbortController.new()
            signal = controller.signal

            setTimeout(create_once_callable(controller.abort), timeout * 1000)
            fetch_response = await pyfetch(
                f"{self._base_url}/remote-dispatch",
                method="POST",
                headers=headers,
                body=json.dumps(body),
                signal=signal,
            )

            if not fetch_response.ok:
                status = fetch_response.status
                text = await fetch_response.text()
                raise NaradaError(f"Failed to dispatch request: {status} {text}")

            request_id = (await fetch_response.json())["requestId"]

            while (now := time.monotonic()) < deadline:
                abort_controller = AbortController.new()
                signal = abort_controller.signal

                setTimeout(
                    create_once_callable(abort_controller.abort),
                    (deadline - now) * 1000,
                )
                fetch_response = await pyfetch(
                    f"{self._base_url}/remote-dispatch/responses/{request_id}",
                    headers=headers,
                    signal=signal,
                )

                if not fetch_response.ok:
                    status = fetch_response.status
                    text = await fetch_response.text()
                    raise NaradaError(f"Failed to poll for response: {status} {text}")

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
        variables: dict[str, str] | None = None,
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
        variables: dict[str, str] | None = None,
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
        variables: dict[str, str] | None = None,
        timeout: int = 120,
    ) -> AgentResponse:
        """Invokes an agent in the Narada extension side panel chat."""
        remote_dispatch_response = await self.dispatch_request(
            prompt=prompt,
            agent=agent,
            clear_chat=clear_chat,
            generate_gif=generate_gif,
            output_schema=output_schema,
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
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["x-api-key"] = self._api_key
        else:
            assert self._user_id is not None
            assert self._env is not None

            headers["Authorization"] = f"Bearer {await _narada_get_id_token()}"
            headers["X-Narada-User-ID"] = self._user_id
            headers["X-Narada-Env"] = self._env

        body = {
            "action": request.model_dump(),
            "browserWindowId": self.browser_window_id,
        }
        if timeout is not None:
            body["timeout"] = timeout

        fetch_response = await pyfetch(
            "https://api.narada.ai/fast/v2/extension-actions",
            method="POST",
            headers=headers,
            body=json.dumps(body),
            # Don't specify `timeout` here as the (soft) timeout is handled by the server.
        )

        if fetch_response.status == HTTPStatus.GATEWAY_TIMEOUT:
            raise NaradaTimeoutError
        elif not fetch_response.ok:
            status = fetch_response.status
            text = await fetch_response.text()
            raise NaradaError(f"Failed to run extension action: {status} {text}")

        resp_json = await fetch_response.json()

        response = ExtensionActionResponse.model_validate(resp_json)
        if response.status == "error":
            raise NaradaError(response.error)

        if response_model is None:
            return None

        assert response.data is not None
        return response_model.model_validate_json(response.data)


class LocalBrowserWindow(BaseBrowserWindow):
    def __init__(self) -> None:
        env = os.environ.get("NARADA_ENV")
        if env is not None and env not in ("prod", "dev"):
            raise ValueError(f"Invalid environment: {env!r}")

        super().__init__(
            api_key=os.environ.get("NARADA_API_KEY"),
            base_url=os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2"),
            user_id=os.environ.get("NARADA_USER_ID"),
            env=env,
            browser_window_id=os.environ["NARADA_BROWSER_WINDOW_ID"],
        )

    def __str__(self) -> str:
        return f"LocalBrowserWindow(browser_window_id={self.browser_window_id})"


class RemoteBrowserWindow(BaseBrowserWindow):
    def __init__(self, *, browser_window_id: str, api_key: str | None = None) -> None:
        super().__init__(
            api_key=api_key or os.environ["NARADA_API_KEY"],
            base_url=os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2"),
            user_id=None,
            env=None,
            browser_window_id=browser_window_id,
        )

    def __str__(self) -> str:
        return f"RemoteBrowserWindow(browser_window_id={self.browser_window_id})"

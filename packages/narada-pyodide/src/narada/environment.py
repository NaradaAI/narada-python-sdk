import asyncio
import builtins
import inspect
import json
import logging
import mimetypes
import os
import time
from abc import ABC
from dataclasses import dataclass
from http import HTTPStatus
from io import IOBase
from pathlib import Path
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Literal,
    Mapping,
    Optional,
    TypedDict,
    TypeGuard,
    TypeVar,
    cast,
    overload,
    override,
)
from urllib.parse import urlencode

from js import AbortController, setTimeout  # type: ignore
from narada_core.actions.models import (
    DEFAULT_HITL_TIMEOUT_SECONDS,
    ActiveInputRequest,
    AgenticMatchingSelectorsFinderRequest,
    AgenticMatchingSelectorsFinderResponse,
    AgenticMouseAction,
    AgenticMouseActionRequest,
    AgenticSelectorAction,
    AgenticSelectorRequest,
    AgenticSelectorResponse,
    AgenticSelectors,
    CloseWindowRequest,
    ExtensionActionRequest,
    ExtensionActionResponse,
    GetFullHtmlRequest,
    GetFullHtmlResponse,
    GetScreenshotRequest,
    GetScreenshotResponse,
    GetSimplifiedHtmlRequest,
    GetSimplifiedHtmlResponse,
    GetUrlRequest,
    GetUrlResponse,
    GoToUrlRequest,
    PrintMessageRequest,
    PromptForUserInputRequest,
    PromptForUserInputResponse,
    PromptForUserInputVariable,
    ReadExcelSheetRequest,
    ReadExcelSheetResponse,
    ReadGoogleSheetRequest,
    ReadGoogleSheetResponse,
    RecordedClick,
    UserApprovalRequest,
    UserApprovalResponse,
    WaitForElementRequest,
    WaitForElementResponse,
    WriteExcelSheetRequest,
    WriteGoogleSheetRequest,
)
from narada_core.errors import (
    NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE,
    NaradaError,
    NaradaTimeoutError,
    UserAbortedError,
)
from narada_core.models import (
    AgentKind,
    File,
    McpServer,
    ReasoningEffort,
    RemoteDispatchChatHistoryItem,
    Response,
    UserResourceCredentials,
    _RemoteDispatchPollResponse,
    _SdkConfig,
)
from packaging.version import Version
from pydantic import BaseModel
from pyodide.ffi import JsProxy, create_once_callable
from pyodide.http import pyfetch

from . import _trace
from .retry import pyfetch_with_retries
from .version import __version__

# Magic variable injected by the JavaScript harness that stores the IDs of the current runnables
# in the stack on the frontend.

logger = logging.getLogger(__name__)


def _parent_run_ids() -> list[str]:
    # `_narada_parent_run_ids` is a Pyodide `JsProxy` object injected by the JavaScript harness.
    # Before we can use it as a regular Python list, we need to call `.to_py()` on it.
    return list(
        cast(
            JsProxy,
            _narada_parent_run_ids,  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
        ).to_py()
    )


def _parent_request_id() -> str | None:
    parent_request_id = getattr(builtins, "_narada_request_id", None)
    if isinstance(parent_request_id, str):
        return parent_request_id
    parent_request_id = globals().get("_narada_request_id")
    return parent_request_id if isinstance(parent_request_id, str) else None


if TYPE_CHECKING:
    # Magic function injected by the JavaScript harness to get the current user's ID token.
    async def _narada_get_id_token() -> str: ...

    _narada_request_id: str | None


_StructuredOutput = TypeVar("_StructuredOutput", bound=BaseModel)

_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)

# Optional remote-dispatch context. In frontend Pyodide runs, these are generated
# by prepare-code.ts; extension-action calls forward them so the parent request
# can report active input-required status.
_REMOTE_DISPATCH_REQUEST_ID_ENV_VAR = "NARADA_REMOTE_DISPATCH_REQUEST_ID"
_REMOTE_DISPATCH_API_KEY_ID_ENV_VAR = "NARADA_REMOTE_DISPATCH_API_KEY_ID"

type InputRequiredCallback = Callable[[ActiveInputRequest], Awaitable[None] | None]


class _InputVariableFileReference(TypedDict):
    source: Literal["remoteDispatchUpload"]
    id: str
    filename: str
    mimeType: str


type _JsonPrimitive = str | int | float | bool | None
type _InputVariableValue = (
    _JsonPrimitive
    | IOBase
    | list["_InputVariableValue"]
    | dict[str, "_InputVariableValue"]
)
type _NormalizedInputVariableValue = (
    _JsonPrimitive
    | _InputVariableFileReference
    | list["_NormalizedInputVariableValue"]
    | dict[str, "_NormalizedInputVariableValue"]
)
type _NormalizedInputVariables = dict[str, _NormalizedInputVariableValue]


class _PresignedPost(BaseModel):
    url: str
    fields: dict[str, Any]


async def _notify_input_required_callback(
    callback: InputRequiredCallback | None,
    response: _RemoteDispatchPollResponse,
    seen_input_ids: set[str],
) -> None:
    if callback is None or response.get("status") != "input-required":
        return

    active_input_request_data = response.get("activeInputRequest")
    if active_input_request_data is None:
        return

    active_input_request = ActiveInputRequest.model_validate(active_input_request_data)
    if active_input_request.input_id in seen_input_ids:
        return

    seen_input_ids.add(active_input_request.input_id)
    callback_result = callback(active_input_request)
    if inspect.isawaitable(callback_result):
        await callback_result


def _trace_agent_type(agent: AgentKind | str) -> str:
    match agent:
        case AgentKind.PRODUCTIVITY:
            return "generalist"
        case AgentKind.OPERATOR:
            return "operator"
        case AgentKind.CORE_AGENT:
            return "coreAgent"
        case _:
            return str(agent)


def _normalize_narada_env(env: str | None) -> Literal["prod", "dev", None]:
    if env is not None and env not in ("prod", "dev"):
        raise ValueError(f"Invalid environment: {env!r}")
    return cast(Literal["prod", "dev", None], env)


async def _build_auth_headers(
    *,
    api_key: str | None,
    user_id: str | None,
    env: Literal["prod", "dev", None],
) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if api_key is not None:
        headers["x-api-key"] = api_key
        return headers

    if user_id is None or env is None:
        raise ValueError(
            "Either `api_key` or all of `user_id` and `env` must be provided"
        )

    headers["Authorization"] = f"Bearer {await _narada_get_id_token()}"
    headers["X-Narada-User-ID"] = user_id
    headers["X-Narada-Env"] = env
    return headers


@dataclass
class SessionDownloadItem:
    """A file downloaded during a cloud browser session (file name, size, presigned GET URL)."""

    file_name: str
    size: int
    download_url: str


class Environment(ABC):
    _api_key: str | None
    _base_url: str
    _user_id: str | None
    _env: Literal["prod", "dev", None]
    _initialized: bool
    _init_lock: asyncio.Lock | None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        user_id: str | None = None,
        env: Literal["prod", "dev", None] = None,
    ) -> None:
        api_key = api_key or os.environ.get("NARADA_API_KEY")
        user_id = user_id or os.environ.get("NARADA_USER_ID")
        env = _normalize_narada_env(env or os.environ.get("NARADA_ENV"))
        if api_key is None and (user_id is None or env is None):
            raise ValueError(
                "Either `api_key` or all of `user_id`, `user_id_token`, and `env` must be provided"
            )

        self._api_key = api_key
        self._base_url = base_url or os.getenv(
            "NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2"
        )
        self._user_id = user_id
        self._env = env
        self._initialized = False
        self._init_lock = None

    @property
    def cloud_browser_session_id(self) -> str | None:
        """Cloud browser session backing this environment, if any.

        Remote dispatch includes this value so backend observability can link a client-mode run to
        an existing SDK-owned cloud browser. Plain local environments are not cloud-backed and
        return `None`; cloud-backed subclasses override this property with their session ID.
        """
        return None

    async def start(self) -> None:
        """Initializes the environment eagerly.

        Initialization is also performed lazily by `Agent.run()` and browser actions. Reusing the
        same environment instance reuses the initialized target.
        """
        await self._ensure_initialized()

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._initialized:
                return

            if self._validates_sdk_config:
                await self._validate_sdk_config()
            await self._initialize()
            self._initialized = True

    @property
    def _validates_sdk_config(self) -> bool:
        return True

    async def _initialize(self) -> None:
        pass

    async def close(self, *, timeout: int | None = None) -> None:
        await self._close_impl(timeout=timeout)

    async def _close_impl(self, *, timeout: int | None = None) -> None:
        pass

    @property
    def _dispatch_browser_window_id(self) -> str | None:
        return None

    async def _fetch_sdk_config(self) -> _SdkConfig | None:
        url = f"{self._base_url}/sdk/config"
        headers = await self._get_auth_headers()

        try:
            resp = await pyfetch(url, headers=headers)
            if not resp.ok:
                logging.warning(
                    "Failed to fetch SDK config: %s %s", resp.status, await resp.text()
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

        package_config = config.packages["narada-pyodide"]
        current_version = Version(__version__)
        min_required_version = Version(package_config.min_required_version)
        if current_version < min_required_version:
            raise RuntimeError(
                f"narada-pyodide<={__version__} is not supported. Please reload the page to "
                f"upgrade to version {package_config.min_required_version} or higher."
            )

    def _current_parent_run_ids(self) -> list[str] | None:
        """Returns the runnable stack to forward with SDK requests.

        Only requests targeting the current browser window should inherit the current runnable
        stack. Remote/cloud browser windows execute in a different frontend instance with an
        independent RunnableEngine, so forwarding parent run IDs would make that frontend treat the
        request as a child runnable of a stack frame it does not have.
        """
        return None

    def _current_parent_request_id(self) -> str | None:
        """Returns the remote-dispatch request that owns the current Python execution."""
        return _parent_request_id()

    async def _get_auth_headers(self) -> dict[str, str]:
        return await _build_auth_headers(
            api_key=self._api_key,
            user_id=self._user_id,
            env=self._env,
        )

    async def _upload_file_impl(self, *, file: IO[Any]) -> File:
        """Uploads a file that can be used as an attachment in a subsequent `Agent.run` request.

        The file is temporarily saved in Narada cloud and expires after 1 day. It can only be
        accessed by the user who uploaded it.
        """
        await self._ensure_initialized()
        # Import browser-only objects lazily so tests and non-browser tooling can import the module.
        from js import Blob, FormData  # type: ignore

        # Get the base filename without directories.
        filename = Path(file.name).name

        seekable = getattr(file, "seekable", None)
        if callable(seekable) and seekable():
            file.seek(0)

        headers = await self._get_auth_headers()
        response = await pyfetch(
            f"{self._base_url}/remote-dispatch/generate-file-upload-presigned-post",
            method="POST",
            headers=headers,
            body=json.dumps({"filename": filename}),
        )
        if not response.ok:
            raise NaradaError(
                "Failed to generate file upload URL: "
                f"{response.status} {await response.text()}"
            )

        presigned_post = _PresignedPost.model_validate(await response.json())
        object_key: str = presigned_post.fields["key"]

        content = file.read()
        if isinstance(content, str):
            content = content.encode()

        # Upload the file with a POST request where:
        # - The URL is the presigned POST URL.
        # - The form fields are the presigned POST fields.
        # - The form data has an addition 'file' field that contains the file contents.
        form_data = FormData.new()
        for key, value in presigned_post.fields.items():
            form_data.append(key, value)
        form_data.append("file", Blob.new([content]), filename)

        upload_response = await pyfetch(
            presigned_post.url,
            method="POST",
            body=form_data,
        )
        if not upload_response.ok:
            raise NaradaError(
                "Failed to upload file: "
                f"{upload_response.status} {await upload_response.text()}"
            )

        return File(key=object_key)

    async def _normalize_input_variables(
        self, *, input_variables: Mapping[str, Any]
    ) -> _NormalizedInputVariables:
        normalized: _NormalizedInputVariables = {}
        for key, value in input_variables.items():
            normalized[key] = await self._normalize_input_variables_value_impl(
                input_variable_value=value
            )
        return normalized

    async def _normalize_input_variables_value_impl(
        self, *, input_variable_value: Any
    ) -> _NormalizedInputVariableValue:
        if isinstance(input_variable_value, list):
            return [
                await self._normalize_input_variables_value_impl(
                    input_variable_value=item
                )
                for item in input_variable_value
            ]

        if self._is_uploadable_file(input_variable_value):
            return await self._upload_input_variable_file(
                input_variable_value=input_variable_value
            )

        if isinstance(input_variable_value, dict):
            normalized: dict[str, _NormalizedInputVariableValue] = {}
            for key, value in input_variable_value.items():
                normalized[key] = await self._normalize_input_variables_value_impl(
                    input_variable_value=value
                )
            return normalized

        return input_variable_value

    @staticmethod
    def _is_uploadable_file(value: Any) -> TypeGuard[IO[Any]]:
        # Keep runtime eligibility aligned with the existing file-upload transport.
        return isinstance(value, IOBase) and hasattr(value, "name")

    async def _upload_input_variable_file(
        self, *, input_variable_value: IO[Any]
    ) -> _InputVariableFileReference:
        filename = Path(input_variable_value.name).name
        uploaded_file = await self._upload_file_impl(file=input_variable_value)
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return {
            "source": "remoteDispatchUpload",
            "id": uploaded_file["key"],
            "filename": filename,
            "mimeType": mime_type,
        }

    # `reasoning` is only valid with the Core Agent; these two overloads make
    # that constraint type-checkable. Generic-agent calls fall through to the
    # general overloads below, which do not accept a `reasoning` argument.
    @overload
    async def _dispatch_request(
        self,
        *,
        prompt: str,
        agent: Literal[AgentKind.CORE_AGENT],
        reasoning: ReasoningEffort | None = None,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: None = None,
        previous_request_id: str | None = None,
        chat_history: list[RemoteDispatchChatHistoryItem] | None = None,
        additional_context: dict[str, str] | None = None,
        attachment: File | IO[Any] | None = None,
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        mcp_servers: list[McpServer] | None = None,
        secret_variables: dict[str, str] | None = None,
        input_variables: Mapping[str, Any] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, Any] | None = None,
        on_input_required: InputRequiredCallback | None = None,
        timeout: int = 1000,
    ) -> Response[None]: ...

    @overload
    async def _dispatch_request(
        self,
        *,
        prompt: str,
        agent: Literal[AgentKind.CORE_AGENT],
        reasoning: ReasoningEffort | None = None,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: type[_StructuredOutput],
        previous_request_id: str | None = None,
        chat_history: list[RemoteDispatchChatHistoryItem] | None = None,
        additional_context: dict[str, str] | None = None,
        attachment: File | IO[Any] | None = None,
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        mcp_servers: list[McpServer] | None = None,
        secret_variables: dict[str, str] | None = None,
        input_variables: Mapping[str, Any] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, Any] | None = None,
        on_input_required: InputRequiredCallback | None = None,
        timeout: int = 1000,
    ) -> Response[_StructuredOutput]: ...

    @overload
    async def _dispatch_request(
        self,
        *,
        prompt: str,
        agent: AgentKind | str = AgentKind.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: None = None,
        previous_request_id: str | None = None,
        chat_history: list[RemoteDispatchChatHistoryItem] | None = None,
        additional_context: dict[str, str] | None = None,
        attachment: File | IO[Any] | None = None,
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        mcp_servers: list[McpServer] | None = None,
        secret_variables: dict[str, str] | None = None,
        input_variables: Mapping[str, Any] | None = None,
        critic_context: dict[str, Any] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, Any] | None = None,
        on_input_required: InputRequiredCallback | None = None,
        timeout: int = 1000,
    ) -> Response[None]: ...

    @overload
    async def _dispatch_request(
        self,
        *,
        prompt: str,
        agent: AgentKind | str = AgentKind.OPERATOR,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: type[_StructuredOutput],
        previous_request_id: str | None = None,
        chat_history: list[RemoteDispatchChatHistoryItem] | None = None,
        additional_context: dict[str, str] | None = None,
        attachment: File | IO[Any] | None = None,
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        mcp_servers: list[McpServer] | None = None,
        secret_variables: dict[str, str] | None = None,
        input_variables: Mapping[str, Any] | None = None,
        critic_context: dict[str, Any] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, Any] | None = None,
        on_input_required: InputRequiredCallback | None = None,
        timeout: int = 1000,
    ) -> Response[_StructuredOutput]: ...

    async def _dispatch_request(
        self,
        *,
        prompt: str,
        agent: AgentKind | str = AgentKind.OPERATOR,
        reasoning: ReasoningEffort | None = None,
        clear_chat: bool | None = None,
        generate_gif: bool | None = None,
        output_schema: type[BaseModel] | None = None,
        previous_request_id: str | None = None,
        chat_history: list[RemoteDispatchChatHistoryItem] | None = None,
        additional_context: dict[str, str] | None = None,
        attachment: File | IO[Any] | None = None,
        time_zone: str = "America/Los_Angeles",
        user_resource_credentials: UserResourceCredentials | None = None,
        mcp_servers: list[McpServer] | None = None,
        secret_variables: dict[str, str] | None = None,
        input_variables: Mapping[str, Any] | None = None,
        critic_context: dict[str, Any] | None = None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, Any] | None = None,
        on_input_required: InputRequiredCallback | None = None,
        timeout: int = 1000,
    ) -> Response:
        """Low-level API for invoking an agent in the Narada extension side panel chat.

        The higher-level `Agent.run` method should be preferred for most use cases.
        """
        # The overloads enforce this at type-check time when callers use
        # ``AgentKind.CORE_AGENT``; the runtime check covers string-form agents
        # (``agent="..."``) and callers without a type checker.
        await self._ensure_initialized()

        if reasoning is not None and agent is not AgentKind.CORE_AGENT:
            raise ValueError(
                "`reasoning` is only supported with `agent=AgentKind.CORE_AGENT` "
                f"(got agent={agent!r})"
            )
        # Trace instrumentation: the entire method body is wrapped so that any
        # exit (successful return, timeout, or non-timeout failure) produces a
        # ``subAgentCall`` trace event with matching status. See `_trace.py`.
        trace_start_ms = _trace.now_ms()
        agent_type_str = _trace_agent_type(agent)

        deadline = time.monotonic() + timeout

        headers = await self._get_auth_headers()

        agent_prefix = (
            agent.prompt_prefix() if isinstance(agent, AgentKind) else f"{agent} "
        )
        body: dict[str, Any] = {
            "prompt": agent_prefix + prompt,
            "timeZone": time_zone,
        }
        browser_window_id = self._dispatch_browser_window_id
        if browser_window_id is not None:
            body["browserWindowId"] = browser_window_id
        parent_run_ids = self._current_parent_run_ids()
        if parent_run_ids:
            body["parentRunIds"] = parent_run_ids
        parent_request_id = self._current_parent_request_id()
        if parent_request_id is not None:
            body["parentRequestId"] = parent_request_id
        cloud_browser_session_id = self.cloud_browser_session_id
        if cloud_browser_session_id is not None:
            body["cloudBrowserSessionId"] = cloud_browser_session_id
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
            if hasattr(attachment, "read") and hasattr(attachment, "name"):
                body["attachment"] = await self._upload_file_impl(file=attachment)
            else:
                body["attachment"] = attachment
        if user_resource_credentials is not None:
            body["userResourceCredentials"] = user_resource_credentials
        if mcp_servers is not None:
            body["mcpServers"] = [
                server.model_dump(mode="json") for server in mcp_servers
            ]
        if secret_variables is not None:
            body["secretVariables"] = secret_variables
        if input_variables is not None:
            body["inputVariables"] = await self._normalize_input_variables(
                input_variables=input_variables
            )
        if critic_context is not None:
            body["criticContext"] = critic_context
        if callback_url is not None:
            body["callbackUrl"] = callback_url
        if callback_secret is not None:
            body["callbackSecret"] = callback_secret
        if callback_headers is not None:
            body["callbackHeaders"] = callback_headers
        if reasoning is not None:
            body["reasoningMode"] = reasoning.value

        try:
            seen_input_ids: set[str] = set()
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
                fetch_response = await pyfetch_with_retries(
                    f"{self._base_url}/remote-dispatch/responses/{request_id}",
                    headers=headers,
                    signal=signal,
                    retry_deadline=deadline,
                )

                if not fetch_response.ok:
                    status = fetch_response.status
                    text = await fetch_response.text()
                    raise NaradaError(f"Failed to poll for response: {status} {text}")

                response: _RemoteDispatchPollResponse = await fetch_response.json()
                response["requestId"] = request_id

                if response["completedAt"] is None:
                    await _notify_input_required_callback(
                        on_input_required,
                        response,
                        seen_input_ids,
                    )
                    # Poll every 3 seconds.
                    await asyncio.sleep(3)
                    continue

                response_content = response["response"]
                if response_content is not None:
                    # Populate the `structuredOutput` field. This is a client-side field
                    # that's not directly returned by the API.
                    output_data = response_content.get("output")
                    if (
                        output_schema is not None
                        and output_data is not None
                        and output_data.get("type") == "structured"
                    ):
                        response_content["structuredOutput"] = (
                            output_schema.model_validate(output_data["content"])
                        )
                    else:
                        response_content["structuredOutput"] = None

                trace_status = cast(_trace.SubAgentCallStatus, response["status"])
                trace_error: str | None = (
                    response_content.get("text")
                    if response["status"] == "error" and response_content is not None
                    else None
                )
                trace_text: str | None = (
                    response_content.get("text")
                    if response["status"] in ("success", "input-required")
                    and response_content is not None
                    else None
                )
                _trace.emit_sub_agent_call(
                    ts_start=trace_start_ms,
                    agent_type=agent_type_str,
                    prompt=prompt,
                    status=trace_status,
                    request_id=request_id,
                    text=trace_text,
                    error_message=trace_error,
                    action_trace_raw=(
                        response_content.get("actionTrace")
                        if response_content is not None
                        else None
                    ),
                )
                return cast(Response, response)
            else:
                raise NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(timeout)

        except NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE:
            _trace.emit_sub_agent_call(
                ts_start=trace_start_ms,
                agent_type=agent_type_str,
                prompt=prompt,
                status="timeout",
                error_message=f"Timed out after {timeout}s",
            )
            raise
        except asyncio.TimeoutError:
            _trace.emit_sub_agent_call(
                ts_start=trace_start_ms,
                agent_type=agent_type_str,
                prompt=prompt,
                status="timeout",
                error_message=f"Timed out after {timeout}s",
            )
            raise NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(timeout)
        except Exception as err:
            _trace.emit_sub_agent_call(
                ts_start=trace_start_ms,
                agent_type=agent_type_str,
                prompt=prompt,
                status="error",
                error_message=str(err),
            )
            raise

    async def _agentic_selector(
        self,
        *,
        action: AgenticSelectorAction,
        selectors: AgenticSelectors,
        fallback_operator_query: str,
        # Larger default timeout because Operator can take a bit to run.
        timeout: int | None = 300,
    ) -> AgenticSelectorResponse:
        """Performs an action on an element specified by the given selectors, falling back to using
        the Operator agent if the selectors fail to match a unique element.

        Returns AgenticSelectorResponse with the value for 'get_text' and 'get_property' actions,
        otherwise returns None.
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
                fallback_operator_query=fallback_operator_query,
            ),
            response_model,
            timeout=timeout,
        )

        if result is None:
            return AgenticSelectorResponse(value=None)

        return result

    async def _agentic_matching_selectors_finder(
        self,
        *,
        prompt: str,
        timeout: int | None = 300,
    ) -> list[AgenticSelectors]:
        """Finds all visible targets matching a prompt and returns selectors."""
        result = await self._run_extension_action(
            AgenticMatchingSelectorsFinderRequest(prompt=prompt),
            AgenticMatchingSelectorsFinderResponse,
            timeout=timeout,
        )
        return result.selectors

    async def _agentic_mouse_action(
        self,
        *,
        action: AgenticMouseAction,
        recorded_click: RecordedClick,
        resize_window: Optional[bool] = True,
        fallback_operator_query: str,
        timeout: int | None = 60,
    ) -> None:
        """Performs a mouse action at the specified click coordinates, falling back to using
        the Operator agent if the click fails.
        """
        return await self._run_extension_action(
            AgenticMouseActionRequest(
                action=action,
                recorded_click=recorded_click,
                resize_window=resize_window or True,
                fallback_operator_query=fallback_operator_query,
            ),
            timeout=timeout,
        )

    async def _close_browser_window(self, *, timeout: int | None = None) -> None:
        """Gracefully closes the current browser window."""
        return await self._run_extension_action(CloseWindowRequest(), timeout=timeout)

    async def _go_to_url(
        self, *, url: str, new_tab: bool = False, timeout: int | None = None
    ) -> None:
        """Navigates the active page in this window to the given URL."""
        return await self._run_extension_action(
            GoToUrlRequest(url=url, new_tab=new_tab), timeout=timeout
        )

    async def _wait_for_element(
        self,
        *,
        selectors: AgenticSelectors,
        state: Literal["visible", "hidden"],
        timeout: int,
    ) -> bool:
        """Waits for an element matching the given selectors to reach the specified state.

        Returns True if the element was found, False if no selector matched before timeout.
        """
        result = await self._run_extension_action(
            WaitForElementRequest(selectors=selectors, state=state, timeout=timeout),
            WaitForElementResponse,
            timeout=timeout // 1000 + 30,
        )
        if result is None:
            return False
        return result.found

    async def _get_url(self, *, timeout: int | None = None) -> GetUrlResponse:
        """Gets the URL of the current active page."""
        result = await self._run_extension_action(
            GetUrlRequest(),
            GetUrlResponse,
            timeout=timeout,
        )
        return result

    async def _print_message(self, *, message: str, timeout: int | None = None) -> None:
        """Prints a message in the Narada extension side panel chat."""
        return await self._run_extension_action(
            PrintMessageRequest(message=message), timeout=timeout
        )

    async def _prompt_for_user_input(
        self,
        *,
        step_id: str,
        variables: list[PromptForUserInputVariable],
        prompt_message: str | None = None,
        timeout: int | None = DEFAULT_HITL_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Prompts the user for one or more input values in the extension UI."""
        result = await self._run_extension_action(
            PromptForUserInputRequest(
                step_id=step_id, prompt_message=prompt_message, variables=variables
            ),
            PromptForUserInputResponse,
            timeout=timeout,
        )
        return result.values_by_name

    async def _user_approval(
        self,
        *,
        step_id: str,
        prompt_message: str,
        approve_label: str,
        reject_label: str,
        timeout: int | None = DEFAULT_HITL_TIMEOUT_SECONDS,
    ) -> bool:
        """Prompts the user to approve or reject in the extension UI."""
        result = await self._run_extension_action(
            UserApprovalRequest(
                step_id=step_id,
                prompt_message=prompt_message,
                approve_label=approve_label,
                reject_label=reject_label,
            ),
            UserApprovalResponse,
            timeout=timeout,
        )
        return result.approved

    async def _read_google_sheet(
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

    async def _read_excel_sheet(
        self,
        *,
        workbook_url: str,
        range: str,
        microsoft_account_email: str,
        timeout: int | None = None,
    ) -> ReadExcelSheetResponse:
        """Reads a range of cells from a Microsoft Excel workbook."""
        return await self._run_extension_action(
            ReadExcelSheetRequest(
                workbook_url=workbook_url,
                range=range,
                microsoft_account_email=microsoft_account_email,
            ),
            ReadExcelSheetResponse,
            timeout=timeout,
        )

    async def _write_google_sheet(
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

    async def _write_excel_sheet(
        self,
        *,
        workbook_url: str,
        range: str,
        microsoft_account_email: str,
        values: list[list[str]],
        timeout: int | None = None,
    ) -> None:
        """Writes a range of cells to a Microsoft Excel workbook."""
        return await self._run_extension_action(
            WriteExcelSheetRequest(
                workbook_url=workbook_url,
                range=range,
                microsoft_account_email=microsoft_account_email,
                values=values,
            ),
            timeout=timeout,
        )

    async def _get_full_html(
        self, *, timeout: int | None = None
    ) -> GetFullHtmlResponse:
        """Gets the full HTML content of the current page."""
        return await self._run_extension_action(
            GetFullHtmlRequest(),
            GetFullHtmlResponse,
            timeout=timeout,
        )

    async def _get_simplified_html(
        self, *, timeout: int | None = None
    ) -> GetSimplifiedHtmlResponse:
        """Gets the simplified HTML content of the current page."""
        return await self._run_extension_action(
            GetSimplifiedHtmlRequest(),
            GetSimplifiedHtmlResponse,
            timeout=timeout,
        )

    async def _get_screenshot(
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
        await self._ensure_initialized()
        browser_window_id = self._dispatch_browser_window_id
        if browser_window_id is None:
            raise NaradaError(
                f"{type(self).__name__} does not support browser extension actions"
            )

        # Trace instrumentation: every exit path emits an ``extensionAction``
        # trace event with a status matching the outcome. See `_trace.py`.
        trace_start_ms = _trace.now_ms()

        try:
            headers = await self._get_auth_headers()

            body = {
                "action": request.model_dump(),
                "browserWindowId": browser_window_id,
            }
            remote_dispatch_request_id = os.environ.get(
                _REMOTE_DISPATCH_REQUEST_ID_ENV_VAR
            )
            remote_dispatch_api_key_id = os.environ.get(
                _REMOTE_DISPATCH_API_KEY_ID_ENV_VAR
            )
            if remote_dispatch_api_key_id is not None:
                body["apiKeyId"] = remote_dispatch_api_key_id
            parent_run_ids = self._current_parent_run_ids()
            if parent_run_ids:
                body["parentRunIds"] = parent_run_ids
            # The env-injected remote-dispatch request id identifies the request the
            # external caller is polling (and that the frontend status reporter
            # targets), so it must take precedence over the builtins parent request
            # id, which for nested runs is a separate observability dispatch id.
            request_id_for_action = (
                remote_dispatch_request_id or self._current_parent_request_id()
            )
            if request_id_for_action is not None:
                body["requestId"] = request_id_for_action
            if timeout is not None:
                body["timeout"] = timeout

            fetch_response = await pyfetch(
                f"{self._base_url}/extension-actions",
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
            workflow_trace = getattr(response, "workflowTrace", None)
            if workflow_trace is not None:
                _trace.emit_sub_workflow(workflow_trace=workflow_trace)
            if response.status == "error":
                raise NaradaError(response.error)
            if response.status == "aborted":
                raise UserAbortedError

            if response_model is None:
                _trace.emit_extension_action(
                    ts_start=trace_start_ms,
                    request=request,
                    status="success",
                )
                return None

            assert response.data is not None
            parsed_response = response_model.model_validate_json(response.data)
            _trace.emit_extension_action(
                ts_start=trace_start_ms,
                request=request,
                status="success",
                response=parsed_response,
            )
            return parsed_response

        except NaradaTimeoutError:
            _trace.emit_extension_action(
                ts_start=trace_start_ms,
                request=request,
                status="timeout",
                error_message="Extension action timed out",
            )
            raise
        except Exception as err:
            _trace.emit_extension_action(
                ts_start=trace_start_ms,
                request=request,
                status="error",
                error_message=str(err),
            )
            raise


class BaseBrowserEnvironment(Environment):
    _browser_window_id: str | None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        user_id: str | None = None,
        env: Literal["prod", "dev", None] = None,
        browser_window_id: str | None = None,
        initialized: bool = False,
    ) -> None:
        super().__init__(
            api_key=api_key,
            user_id=user_id,
            env=env,
        )
        self._browser_window_id = browser_window_id
        self._initialized = initialized

    @property
    def browser_window_id(self) -> str:
        if self._browser_window_id is None:
            raise RuntimeError(
                "Browser environment is not initialized yet. Call `await env.start()` "
                "or run an agent action first."
            )
        return self._browser_window_id

    @property
    def _dispatch_browser_window_id(self) -> str | None:
        return self.browser_window_id


class BrowserEnvironment(BaseBrowserEnvironment):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        user_id: str | None = None,
        env: Literal["prod", "dev", None] = None,
        browser_window_id: str | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            user_id=user_id,
            env=env,
            browser_window_id=browser_window_id
            or os.environ["NARADA_BROWSER_WINDOW_ID"],
        )

    def __str__(self) -> str:
        return f"BrowserEnvironment(browser_window_id={self.browser_window_id})"

    @override
    def _current_parent_run_ids(self) -> list[str] | None:
        return _parent_run_ids()

    @override
    async def _close_impl(self, *, timeout: int | None = None) -> None:
        await self._close_browser_window(timeout=timeout)


class RemoteBrowserEnvironment(BaseBrowserEnvironment):
    def __init__(
        self,
        *,
        browser_window_id: str,
        cloud_browser_session_id: str | None = None,
        api_key: str | None = None,
        user_id: str | None = None,
        env: Literal["prod", "dev", None] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            user_id=user_id,
            env=env,
            browser_window_id=browser_window_id,
            initialized=True,
        )
        self._cloud_browser_session_id = cloud_browser_session_id

    @property
    def _validates_sdk_config(self) -> bool:
        return False

    @property
    def cloud_browser_session_id(self) -> str | None:
        return self._cloud_browser_session_id

    @override
    async def _close_impl(self, *, timeout: int | None = None) -> None:
        """Closes the browser environment or stops the backing cloud session."""
        if self._cloud_browser_session_id is None:
            return await self._close_browser_window(timeout=timeout)

        await _stop_cloud_browser_session(
            base_url=self._base_url,
            auth_headers=await self._get_auth_headers(),
            session_id=self._cloud_browser_session_id,
            timeout=timeout,
        )

    async def get_downloaded_files(self) -> list[SessionDownloadItem]:
        """Return files downloaded during this cloud browser session (file name, size, presigned GET URL per file)."""
        if self._cloud_browser_session_id is None:
            raise ValueError(
                "Cloud browser session ID is required to get downloaded files"
            )

        return await _get_cloud_browser_downloads(
            base_url=self._base_url,
            auth_headers=await self._get_auth_headers(),
            session_id=self._cloud_browser_session_id,
        )

    def __str__(self) -> str:
        return f"RemoteBrowserEnvironment(browser_window_id={self.browser_window_id})"


class CloudBrowserEnvironment(BaseBrowserEnvironment):
    def __init__(
        self,
        *,
        session_name: str | None = None,
        session_timeout: int | None = None,
        api_key: str | None = None,
        user_id: str | None = None,
        env: Literal["prod", "dev", None] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            user_id=user_id,
            env=env,
        )
        self._session_name = session_name
        self._session_timeout = session_timeout
        self._session_id: str | None = None

    @property
    def cloud_browser_session_id(self) -> str:
        if self._session_id is None:
            raise RuntimeError(
                "Cloud browser environment is not initialized yet. Call `await env.start()` "
                "or run an agent action first."
            )
        return self._session_id

    async def _initialize(self) -> None:
        response_data = await _create_and_initialize_cloud_browser_session(
            base_url=self._base_url,
            auth_headers=await self._get_auth_headers(),
            session_name=self._session_name,
            session_timeout=self._session_timeout,
            require_extension=True,
        )
        self._browser_window_id = response_data["browser_window_id"]
        self._session_id = response_data["session_id"]

    @override
    async def _close_impl(self, *, timeout: int | None = None) -> None:
        """Stops the cloud browser session."""
        if self._session_id is not None:
            await _stop_cloud_browser_session(
                base_url=self._base_url,
                auth_headers=await self._get_auth_headers(),
                session_id=self._session_id,
                timeout=timeout,
            )

    async def get_downloaded_files(self) -> list[SessionDownloadItem]:
        """Return files downloaded during this cloud browser session (file name, size, presigned GET URL per file)."""
        return await _get_cloud_browser_downloads(
            base_url=self._base_url,
            auth_headers=await self._get_auth_headers(),
            session_id=self.cloud_browser_session_id,
        )

    def __str__(self) -> str:
        return (
            "CloudBrowserEnvironment("
            f"cloud_browser_session_id={self._session_id}, "
            f"browser_window_id={self.browser_window_id}"
            ")"
        )


class LambdaEnvironment(Environment):
    """Cloud execution environment without browser actions."""

    def __init__(
        self,
        *,
        session_name: str | None = None,
        session_timeout: int | None = None,
        api_key: str | None = None,
        user_id: str | None = None,
        env: Literal["prod", "dev", None] = None,
    ) -> None:
        super().__init__(api_key=api_key, user_id=user_id, env=env)
        self._session_name = session_name
        self._session_timeout = session_timeout
        self._session_id: str | None = None
        self._browser_window_id: str | None = None

    @property
    def session_id(self) -> str:
        if self._session_id is None:
            raise RuntimeError(
                "Lambda environment is not initialized yet. Call `await env.start()` "
                "or run an agent first."
            )
        return self._session_id

    @property
    def cloud_browser_session_id(self) -> str | None:
        return self._session_id

    @property
    def _dispatch_browser_window_id(self) -> str | None:
        return self._browser_window_id

    async def _initialize(self) -> None:
        response_data = await _create_and_initialize_cloud_browser_session(
            base_url=self._base_url,
            auth_headers=await self._get_auth_headers(),
            session_name=self._session_name,
            session_timeout=self._session_timeout,
            require_extension=False,
        )
        self._browser_window_id = response_data["browser_window_id"]
        self._session_id = response_data["session_id"]

    async def _close_impl(self, *, timeout: int | None = None) -> None:
        if self._session_id is not None:
            await _stop_cloud_browser_session(
                base_url=self._base_url,
                auth_headers=await self._get_auth_headers(),
                session_id=self._session_id,
                timeout=timeout,
            )


async def _create_and_initialize_cloud_browser_session(
    *,
    base_url: str,
    auth_headers: dict[str, str],
    session_name: str | None,
    session_timeout: int | None,
    require_extension: bool,
) -> dict[str, Any]:
    endpoint_url = (
        f"{base_url}/cloud-browser/create-and-initialize-cloud-browser-session"
    )
    request_body: dict[str, Any] = {
        "session_name": session_name,
        "session_timeout": session_timeout,
        "require_extension": require_extension,
    }
    initiator_remote_dispatch_request_id = os.environ.get(
        "NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID", ""
    ).strip()
    if not initiator_remote_dispatch_request_id:
        raise ValueError("NARADA_INITIATOR_REMOTE_DISPATCH_REQUEST_ID is required")
    request_body["initiator_remote_dispatch_request_id"] = (
        initiator_remote_dispatch_request_id
    )

    response = None
    max_attempts = 3
    retry_backoff_seconds = (2.0, 4.0, 0.0)  # no wait after last attempt
    for attempt in range(max_attempts):
        # Due to unknown network issues, sometimes create-and-initialize-cloud-browser-session API call fails.
        try:
            response = await pyfetch(
                endpoint_url,
                method="POST",
                headers=auth_headers,
                body=json.dumps(request_body),
            )
            if response.ok:
                break
        except Exception:
            await asyncio.sleep(retry_backoff_seconds[attempt])
            continue

    if response is None or not response.ok:
        resp_status = response.status if response is not None else "unknown status"
        resp_text = await response.text() if response is not None else "unknown error"
        raise RuntimeError(
            "Failed to create and initialize cloud browser session after 3 attempts with backoff: "
            f"{resp_status}: {resp_text}\n"
            f"Endpoint URL: {endpoint_url}"
        )

    return await response.json()


def _build_cloud_browser_url(
    base_url: str, path: str, *, params: dict[str, str] | None = None
) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


async def _fetch_presigned_download_url(
    *,
    base_url: str,
    auth_headers: dict[str, str],
    session_id: str,
    key: str,
) -> str:
    fetch_response = await pyfetch_with_retries(
        _build_cloud_browser_url(
            base_url,
            "/cloud-browser/replay/download-url",
            params={"session_id": session_id, "key": key},
        ),
        headers=auth_headers,
    )
    if not fetch_response.ok:
        raise NaradaError(
            "Failed to fetch cloud browser download URL: "
            f"{fetch_response.status} {await fetch_response.text()}"
        )
    data = await fetch_response.json()
    return data["presigned_url"]


async def _get_cloud_browser_downloads(
    *,
    base_url: str,
    auth_headers: dict[str, str],
    session_id: str,
) -> list[SessionDownloadItem]:
    fetch_response = await pyfetch_with_retries(
        _build_cloud_browser_url(
            base_url,
            "/cloud-browser/replay/downloads",
            params={"session_id": session_id},
        ),
        headers=auth_headers,
    )
    if not fetch_response.ok:
        raise NaradaError(
            "Failed to fetch cloud browser downloads: "
            f"{fetch_response.status} {await fetch_response.text()}"
        )

    data = await fetch_response.json()
    files = data.get("downloaded_files") or []
    if not files:
        return []

    presigned_urls = await asyncio.gather(
        *[
            _fetch_presigned_download_url(
                base_url=base_url,
                auth_headers=auth_headers,
                session_id=session_id,
                key=item["key"],
            )
            for item in files
        ]
    )
    return [
        SessionDownloadItem(
            file_name=item["file_name"],
            size=item["size"],
            download_url=presigned_urls[index],
        )
        for index, item in enumerate(files)
    ]


async def _stop_cloud_browser_session(
    *,
    base_url: str,
    auth_headers: dict[str, str],
    session_id: str,
    timeout: int | None = None,
) -> None:
    try:
        fetch_response = await pyfetch(
            f"{base_url}/cloud-browser/stop-cloud-browser-session",
            method="POST",
            headers={**auth_headers, "Content-Type": "application/json"},
            body=json.dumps({"session_id": session_id}),
        )
        if not fetch_response.ok:
            logger.warning(
                "Failed to stop session %s: %s", session_id, fetch_response.status
            )
            return

        response_data = await fetch_response.json()
        if not response_data.get("success"):
            logger.warning(
                "Failed to stop session %s: %s",
                session_id,
                response_data.get("message"),
            )
    except Exception as e:
        logger.warning("Error calling stop session endpoint: %s", e)

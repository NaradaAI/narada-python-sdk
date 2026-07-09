from __future__ import annotations

import asyncio
import inspect
import json
import logging
import mimetypes
import os
import random
import subprocess
import sys
import time
from abc import ABC
from dataclasses import dataclass
from http import HTTPStatus
from io import IOBase
from pathlib import Path
from typing import (
    IO,
    Any,
    Awaitable,
    Callable,
    Literal,
    Mapping,
    TypedDict,
    TypeGuard,
    TypeVar,
    cast,
    overload,
    override,
)
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import aiohttp
from narada_core.actions.models import (
    ActiveInputRequest,
    CloseWindowRequest,
    ExtensionActionRequest,
    ExtensionActionResponse,
)
from narada_core.errors import (
    NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE,
    NaradaError,
    NaradaExtensionMissingError,
    NaradaExtensionUnauthenticatedError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
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
from playwright._impl._errors import Error as PlaywrightError
from playwright.async_api import (
    Browser,
    BrowserContext,
    CDPSession,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api._context_manager import PlaywrightContextManager
from pydantic import BaseModel, ValidationError
from rich.console import Console

from narada.config import BrowserConfig, ProxyConfig
from narada.utils import assert_not_none
from narada.version import __version__

logger = logging.getLogger(__name__)

_StructuredOutput = TypeVar("_StructuredOutput", bound=BaseModel)


_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)

# Optional remote-dispatch context. In frontend Pyodide runs, these are generated
# by prepare-code.ts; extension-action calls forward them so the parent request
# can report active input-required status.
_REMOTE_DISPATCH_REQUEST_ID_ENV_VAR = "NARADA_REMOTE_DISPATCH_REQUEST_ID"
_REMOTE_DISPATCH_API_KEY_ID_ENV_VAR = "NARADA_REMOTE_DISPATCH_API_KEY_ID"
_BROWSER_WINDOW_ID_SELECTOR = "#narada-browser-window-id"
_UNSUPPORTED_BROWSER_INDICATOR_SELECTOR = "#narada-unsupported-browser"
_EXTENSION_MISSING_INDICATOR_SELECTOR = "#narada-extension-missing"
_EXTENSION_UNAUTHENTICATED_INDICATOR_SELECTOR = "#narada-extension-unauthenticated"
_INITIALIZATION_ERROR_INDICATOR_SELECTOR = "#narada-initialization-error"
_BROWSER_WINDOW_ID_OBSERVER_KEY = "narada.sdk.browserWindowIdObserver"
_BROWSER_WINDOW_ID_OBSERVER_LEGACY_GLOBAL = "__naradaBrowserWindowIdObserver"


type _BrowserInitializationResultType = Literal[
    "browser_window_id",
    "unsupported_browser",
    "extension_missing",
    "extension_unauthenticated",
    "initialization_error",
]


class _BrowserInitializationResult(TypedDict, total=False):
    type: _BrowserInitializationResultType
    browserWindowId: str


def _build_browser_window_id_observer_script() -> str:
    targets = [
        {
            "type": "unsupported_browser",
            "selector": _UNSUPPORTED_BROWSER_INDICATOR_SELECTOR,
        },
        {
            "type": "extension_missing",
            "selector": _EXTENSION_MISSING_INDICATOR_SELECTOR,
        },
        {
            "type": "extension_unauthenticated",
            "selector": _EXTENSION_UNAUTHENTICATED_INDICATOR_SELECTOR,
        },
        {
            "type": "initialization_error",
            "selector": _INITIALIZATION_ERROR_INDICATOR_SELECTOR,
        },
        {"type": "browser_window_id", "selector": _BROWSER_WINDOW_ID_SELECTOR},
    ]
    script = """
        (() => {
          if (window.top !== window) {
            return;
          }

          const targets = __TARGETS__;
          const globalSymbol = Symbol.for(__GLOBAL_KEY__);
          const legacyGlobalKey = __LEGACY_GLOBAL_KEY__;
          const legacyState = window[legacyGlobalKey];
          if (legacyState !== undefined) {
            cleanupPreviousState(legacyState);
            delete window[legacyGlobalKey];
          }

          const existingState = window[globalSymbol];
          if (existingState?.version === 3) {
            return;
          }

          if (existingState !== undefined) {
            cleanupPreviousState(existingState);
            delete window[globalSymbol];
          }

          const state = {
            version: 3,
            result: null,
            observer: null,
            resolved: false,
            disposed: false,
            resolve: null,
            promise: null,
            readInitializationResult: null,
            dispose: null,
          };

          function cleanup() {
            if (state.observer !== null) {
              state.observer.disconnect();
              state.observer = null;
            }
          }

          function cleanupPreviousState(previousState) {
            previousState?.dispose?.();
            previousState?.observer?.disconnect?.();
            if (
              previousState?.intervalId !== null
              && previousState?.intervalId !== undefined
            ) {
              clearInterval(previousState.intervalId);
            }
          }

          function dispose() {
            state.disposed = true;
            cleanup();
            if (window[globalSymbol] === state) {
              delete window[globalSymbol];
            }
          }

          function readInitializationResult() {
            for (const target of targets) {
              const element = document.querySelector(target.selector);
              if (element === null) {
                continue;
              }

              if (target.type !== 'browser_window_id') {
                return { type: target.type };
              }

              const browserWindowId = element.textContent?.trim();
              if (browserWindowId) {
                return { type: target.type, browserWindowId };
              }
            }

            return null;
          }

          function finishIfReady() {
            if (state.disposed) {
              return true;
            }
            const result = readInitializationResult();
            if (result === null) {
              return false;
            }
            if (state.resolved) {
              return true;
            }

            state.resolved = true;
            state.result = result;
            cleanup();
            state.resolve(result);
            return true;
          }

          state.promise = new Promise((resolve) => {
            state.resolve = resolve;
          });
          state.readInitializationResult = readInitializationResult;
          state.dispose = dispose;
          Object.defineProperty(window, globalSymbol, {
            value: state,
            configurable: true,
            writable: true,
          });

          function startObserving() {
            if (finishIfReady()) {
              return;
            }

            const root = document.documentElement ?? document;
            state.observer = new MutationObserver(finishIfReady);
            state.observer.observe(root, {
              childList: true,
              subtree: true,
              characterData: true,
            });
          }

          if (document.documentElement !== null) {
            startObserving();
          } else {
            document.addEventListener('DOMContentLoaded', startObserving, { once: true });
          }
        })();
    """
    return (
        script.replace("__TARGETS__", json.dumps(targets))
        .replace("__GLOBAL_KEY__", json.dumps(_BROWSER_WINDOW_ID_OBSERVER_KEY))
        .replace(
            "__LEGACY_GLOBAL_KEY__",
            json.dumps(_BROWSER_WINDOW_ID_OBSERVER_LEGACY_GLOBAL),
        )
    )


type InputRequiredCallback = Callable[[ActiveInputRequest], Awaitable[None] | None]


def _load_execution_trace_context_from_env() -> dict[str, Any] | None:
    raw = os.environ.get("NARADA_EXECUTION_TRACE_CONTEXT")
    if not raw:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("NARADA_EXECUTION_TRACE_CONTEXT must be a JSON object")
    return value


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
type _InputVariables = dict[str, _InputVariableValue]
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


class _CustomTokenResponse(BaseModel):
    token: str


@dataclass
class SessionDownloadItem:
    """A file downloaded during a cloud browser session (file name, size, presigned GET URL)."""

    file_name: str
    size: int
    download_url: str


@dataclass
class _LaunchBrowserResult:
    playwright_browser: Browser
    browser_process_id: int
    browser_window_id: str
    browser_context: BrowserContext
    side_panel_page: Page | None


def _with_query_params(url: str, params: Mapping[str, str]) -> str:
    parsed_url = urlsplit(url)
    query_params = [
        *parse_qsl(parsed_url.query, keep_blank_values=True),
        *params.items(),
    ]
    return urlunsplit(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            urlencode(query_params),
            parsed_url.fragment,
        )
    )


class ApiErrorPayload(BaseModel):
    detail: Any | None = None

    @classmethod
    def from_error_text(cls, error_text: str | None) -> ApiErrorPayload:
        if not error_text:
            return cls()

        try:
            return cls.model_validate_json(error_text)
        except ValidationError:
            try:
                body = json.loads(error_text)
            except (ValueError, TypeError):
                return cls()

            if isinstance(body, dict):
                return cls(detail=body.get("detail", body))

            return cls()


class _BrowserInitializationHelper:
    def __init__(self, *, console: Console) -> None:
        self._console = console

    @staticmethod
    async def install_browser_window_id_observer(page: Page) -> None:
        await page.add_init_script(script=_build_browser_window_id_observer_script())

    @staticmethod
    async def wait_for_browser_initialization_result(
        page: Page, *, timeout: int
    ) -> _BrowserInitializationResult | None:
        await page.evaluate(_build_browser_window_id_observer_script())
        result = await page.evaluate(
            """
            async ({ globalKey, timeoutMs }) => {
              const observerState = window[Symbol.for(globalKey)];
              const immediateResult =
                observerState?.readInitializationResult?.() ?? null;
              if (immediateResult !== null) {
                return immediateResult;
              }

              if (observerState?.promise === undefined) {
                return null;
              }

              let timeoutId = null;
              const timeoutPromise = new Promise((resolve) => {
                timeoutId = window.setTimeout(
                  () => resolve({ type: 'timeout' }),
                  timeoutMs
                );
              });

              const result = await Promise.race([
                observerState.promise,
                timeoutPromise,
              ]);
              if (timeoutId !== null) {
                window.clearTimeout(timeoutId);
              }
              if (result?.type === 'timeout') {
                observerState.dispose?.();
                return null;
              }
              return result;
            }
            """,
            {
                "globalKey": _BROWSER_WINDOW_ID_OBSERVER_KEY,
                "timeoutMs": timeout,
            },
        )
        if not isinstance(result, dict):
            return None

        result_type = result.get("type")
        if result_type not in {
            "browser_window_id",
            "unsupported_browser",
            "extension_missing",
            "extension_unauthenticated",
            "initialization_error",
        }:
            return None

        return cast(_BrowserInitializationResult, result)

    @staticmethod
    async def wait_for_browser_window_id_silently(page: Page, *, timeout: int) -> str:
        result = (
            await _BrowserInitializationHelper.wait_for_browser_initialization_result(
                page,
                timeout=timeout,
            )
        )
        if result is None:
            raise NaradaTimeoutError("Timed out waiting for browser window ID")

        result_type = result.get("type")
        if result_type == "browser_window_id":
            browser_window_id = result.get("browserWindowId")
            if not isinstance(browser_window_id, str) or not browser_window_id:
                raise NaradaInitializationError("Browser window ID is empty")

            return browser_window_id

        # TODO: Create custom exception types for these cases.
        if result_type == "unsupported_browser":
            raise NaradaUnsupportedBrowserError("Unsupported browser")

        if result_type == "extension_missing":
            raise NaradaExtensionMissingError("Narada extension missing")

        if result_type == "extension_unauthenticated":
            raise NaradaExtensionUnauthenticatedError(
                "Sign in to the Narada extension first"
            )

        if result_type == "initialization_error":
            raise NaradaInitializationError("Initialization error")

        raise NaradaInitializationError("Unexpected initialization result")

    async def wait_for_browser_window_id_interactively(
        self, page: Page, *, per_attempt_timeout: int
    ) -> str:
        try:
            while True:
                try:
                    return await _BrowserInitializationHelper.wait_for_browser_window_id_silently(
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
                        "\n[bold]>[/bold] [bold blue]Narada is signing in automatically with your "
                        "SDK credentials. Press Enter to retry if this does not continue.[/bold blue]",
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

    async def wait_for_browser_window_id(
        self,
        initialization_page: Page,
        config: BrowserConfig,
        timeout: int = 30_000,
    ) -> str:
        """Waits for the browser window ID to be available, potentially letting the user respond to
        recoverable errors interactively.
        """
        if config.interactive:
            return await self.wait_for_browser_window_id_interactively(
                initialization_page, per_attempt_timeout=timeout
            )
        else:
            return (
                await _BrowserInitializationHelper.wait_for_browser_window_id_silently(
                    initialization_page, timeout=timeout
                )
            )

    def print_success_message(self, browser_window_id: str) -> None:
        self._console.print(
            "\n[bold]>[/bold] [bold green]Initialization successful. Browser window ID: "
            f"{browser_window_id}[/bold green]\n",
        )


class Environment(ABC):
    _auth_headers: dict[str, str]
    _base_url: str
    _initialized: bool
    _init_lock: asyncio.Lock | None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        auth_headers: dict[str, str] | None = None,
        base_url: str | None = None,
    ) -> None:
        if auth_headers is not None:
            self._auth_headers = auth_headers
        else:
            api_key = api_key or os.environ["NARADA_API_KEY"]
            self._auth_headers = {"x-api-key": api_key}
        self._base_url = base_url or os.getenv(
            "NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2"
        )
        self._console = Console()
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

    async def _detach(self) -> None:
        pass

    @property
    def _dispatch_browser_window_id(self) -> str | None:
        return None

    async def _fetch_sdk_config(self) -> _SdkConfig | None:
        url = f"{self._base_url}/sdk/config"

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

    async def _upload_file_impl(self, *, file: IO[Any]) -> File:
        await self._ensure_initialized()
        # Get the base filename without directories.
        filename = Path(file.name).name

        seekable = getattr(file, "seekable", None)
        if callable(seekable) and seekable():
            file.seek(0)

        async with aiohttp.ClientSession() as session:
            # First generate a presigned POST for uploading the file.
            async with session.post(
                f"{self._base_url}/remote-dispatch/generate-file-upload-presigned-post",
                headers=self._auth_headers,
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
        callback_headers: Mapping[str, Any] | None = None,
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
        callback_headers: Mapping[str, Any] | None = None,
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
        callback_headers: Mapping[str, Any] | None = None,
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
        callback_headers: Mapping[str, Any] | None = None,
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
        callback_headers: Mapping[str, Any] | None = None,
        on_input_required: InputRequiredCallback | None = None,
        timeout: int = 1000,
    ) -> Response:
        """Low-level API for invoking an agent in the Narada extension side panel chat.

        The higher-level `Agent.run` method should be preferred for most use cases.
        """
        await self._ensure_initialized()

        # The overloads enforce this at type-check time when callers use
        # ``AgentKind.CORE_AGENT``; the runtime check covers string-form agents
        # (``agent="..."``) and callers without a type checker.
        if reasoning is not None and agent is not AgentKind.CORE_AGENT:
            raise ValueError(
                "`reasoning` is only supported with `agent=AgentKind.CORE_AGENT` "
                f"(got agent={agent!r})"
            )
        deadline = time.monotonic() + timeout

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
        execution_trace_context = _load_execution_trace_context_from_env()
        if execution_trace_context is not None:
            body["executionTraceContext"] = execution_trace_context
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
            if self._is_uploadable_file(attachment):
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
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/remote-dispatch",
                    headers=self._auth_headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    resp.raise_for_status()
                    request_id = (await resp.json())["requestId"]

                while (now := time.monotonic()) < deadline:
                    async with session.get(
                        f"{self._base_url}/remote-dispatch/responses/{request_id}",
                        headers=self._auth_headers,
                        timeout=aiohttp.ClientTimeout(total=deadline - now),
                    ) as resp:
                        resp.raise_for_status()
                        response: _RemoteDispatchPollResponse = await resp.json()

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

                    return cast(Response, response)
                else:
                    raise NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(timeout)

        except asyncio.TimeoutError:
            raise NaradaAgentTimeoutError_INTERNAL_DO_NOT_USE(timeout)

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
        action_execution_id = f"action_{uuid4().hex}"
        body = {
            "action": request.model_dump(),
            "actionExecutionId": action_execution_id,
            "browserWindowId": browser_window_id,
        }
        remote_dispatch_request_id = os.environ.get(_REMOTE_DISPATCH_REQUEST_ID_ENV_VAR)
        if remote_dispatch_request_id is not None:
            body["requestId"] = remote_dispatch_request_id
        remote_dispatch_api_key_id = os.environ.get(_REMOTE_DISPATCH_API_KEY_ID_ENV_VAR)
        if remote_dispatch_api_key_id is not None:
            body["apiKeyId"] = remote_dispatch_api_key_id
        if timeout is not None:
            body["timeout"] = timeout

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base_url}/extension-actions",
                headers=self._auth_headers,
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
        if response.status == "aborted":
            raise UserAbortedError

        if response_model is None:
            return None

        assert response.data is not None
        return response_model.model_validate_json(response.data)


class BaseBrowserEnvironment(Environment):
    _browser_window_id: str | None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        auth_headers: dict[str, str] | None = None,
        base_url: str | None = None,
        browser_window_id: str | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            auth_headers=auth_headers,
            base_url=base_url,
        )
        self._browser_window_id = browser_window_id
        if browser_window_id is not None:
            self._initialized = True

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


class _PlaywrightLifecycleMixin:
    _config: BrowserConfig
    _context: BrowserContext | None
    _playwright_browser: Browser | None
    _playwright_context_manager: PlaywrightContextManager | None
    _playwright_lifecycle_lock: asyncio.Lock | None
    _playwright: Playwright | None
    _playwright_client_not_connected_message = "Browser client is not connected"

    async def reset_agent_state(self) -> None:
        await self._ensure_initialized()
        # Run reconnect/use/detach one at a time so shared Playwright fields stay valid.
        async with self._acquire_playwright_lifecycle_lock():
            await self._ensure_playwright_connected()
            try:
                side_panel_page = self._get_side_panel_page()

                # Refresh the extension side panel, which ensures any inflight Narada operations are
                # canceled.
                await side_panel_page.reload()
            finally:
                await self._stop_playwright()

    async def _detach(self) -> None:
        # Run detach one at a time with temporary reconnects that mutate Playwright fields.
        async with self._acquire_playwright_lifecycle_lock():
            await self._stop_playwright()

    def _acquire_playwright_lifecycle_lock(self) -> asyncio.Lock:
        if self._playwright_lifecycle_lock is None:
            self._playwright_lifecycle_lock = asyncio.Lock()
        return self._playwright_lifecycle_lock

    async def _start_playwright(self) -> None:
        self._playwright_context_manager = async_playwright()
        self._playwright = await self._playwright_context_manager.__aenter__()

    async def _stop_playwright(self) -> None:
        playwright_browser = self._playwright_browser
        playwright_context_manager = self._playwright_context_manager
        self._playwright_browser = None
        self._context = None
        self._playwright_context_manager = None
        self._playwright = None

        try:
            if playwright_browser is not None:
                await playwright_browser.close()
        finally:
            if playwright_context_manager is not None:
                await playwright_context_manager.__aexit__(None, None, None)

    async def _ensure_playwright_connected(self) -> None:
        if (
            self._playwright_browser is not None
            and self._context is not None
            and self._playwright_context_manager is not None
            and self._playwright is not None
        ):
            return

        await self._stop_playwright()
        await self._start_playwright()

        try:
            self._playwright_browser = await self._connect_playwright_browser()
            self._context = self._playwright_browser.contexts[0]
        except Exception:
            await self._stop_playwright()
            raise

    async def _connect_playwright_browser(self) -> Browser:
        raise NotImplementedError

    def _get_side_panel_page(self) -> Page:
        if self._context is None:
            raise NaradaInitializationError(
                self._playwright_client_not_connected_message
            )

        side_panel_url = create_side_panel_url(self._config, self.browser_window_id)
        side_panel_page = next(
            (p for p in self._context.pages if p.url == side_panel_url), None
        )
        if side_panel_page is None:
            raise NaradaInitializationError(
                f"Could not find Narada side panel page for browser window "
                f"{self.browser_window_id!r}"
            )
        return side_panel_page


class BrowserEnvironment(_PlaywrightLifecycleMixin, BaseBrowserEnvironment):
    _browser_process_id: int | None
    _config: BrowserConfig
    _context: BrowserContext | None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        auth_headers: dict[str, str] | None = None,
        config: BrowserConfig | None = None,
        attach_to_existing: bool = False,
    ) -> None:
        super().__init__(
            api_key=api_key,
            auth_headers=auth_headers,
        )
        self._browser_process_id = None
        self._config = config or BrowserConfig()
        self._context = None
        self._attach_to_existing = attach_to_existing
        self._playwright_browser: Browser | None = None
        self._playwright_lifecycle_lock: asyncio.Lock | None = None
        self._playwright_context_manager: PlaywrightContextManager | None = None
        self._playwright: Playwright | None = None
        self._browser_initialization = _BrowserInitializationHelper(
            console=self._console
        )

    @property
    def browser_process_id(self) -> int | None:
        return self._browser_process_id

    def __str__(self) -> str:
        return (
            "BrowserEnvironment("
            f"browser_process_id={self._browser_process_id}, "
            f"browser_window_id={self._browser_window_id}"
            ")"
        )

    async def _initialize(self) -> None:
        await self._start_playwright()
        try:
            if self._attach_to_existing:
                await self._initialize_in_existing_browser_window()
            else:
                await self._open_and_initialize_browser_window()
        finally:
            try:
                await self._detach()
            except Exception:
                logger.warning(
                    "Failed to detach Playwright resources after browser initialization",
                    exc_info=True,
                )

    @override
    async def _close_impl(self, *, timeout: int | None = None) -> None:
        try:
            if self._initialized and self._browser_window_id is not None:
                await self._run_extension_action(CloseWindowRequest(), timeout=timeout)
        finally:
            await self._detach()

    async def _connect_playwright_browser(self) -> Browser:
        assert self._playwright is not None
        return await self._playwright.chromium.connect_over_cdp(self._config.cdp_url)

    async def _open_and_initialize_browser_window(self) -> None:
        assert self._playwright is not None
        launch_browser_result = await self._launch_browser(
            self._playwright, self._config
        )
        side_panel_page = launch_browser_result.side_panel_page

        await self._fix_download_behavior(
            launch_browser_result.browser_context,
            side_panel_page,
        )

        self._playwright_browser = launch_browser_result.playwright_browser
        self._browser_process_id = launch_browser_result.browser_process_id
        self._browser_window_id = launch_browser_result.browser_window_id
        self._context = launch_browser_result.browser_context

    async def _initialize_in_existing_browser_window(self) -> None:
        """Initializes the Narada extension in an existing browser window.

        This method connects to an existing browser process via CDP and performs the same
        initialization logic as a launched browser, but without launching a new browser process.
        """
        assert self._playwright is not None

        if self._config.proxy is not None:
            raise ValueError(
                "Proxy configuration is not supported for `BrowserEnvironment(..., "
                "attach_to_existing=True)`. Proxy settings must be specified when launching "
                "Chrome. Use `BrowserEnvironment` without `attach_to_existing` instead."
            )

        browser = await self._playwright.chromium.connect_over_cdp(self._config.cdp_url)

        # Generate a unique tag for the initialization URL
        window_tag = uuid4().hex
        tagged_initialization_url = f"{self._config.initialization_url}?t={window_tag}"

        # Open the initialization page in a new tab in the default context.
        context = browser.contexts[0]
        initialization_page = await context.new_page()
        await _BrowserInitializationHelper.install_browser_window_id_observer(
            initialization_page
        )
        await initialization_page.goto(tagged_initialization_url)

        browser_window_id = await self._wait_for_browser_window_id_with_lazy_login(
            initialization_page,
            self._config,
            tagged_initialization_url,
        )

        # Playwright seems unable to pick up the side panel page that is automatically opened by the
        # initialization page. We need to establish a new CDP connection to the browser *after* the
        # side panel page is opened for Playwright to see it.
        await browser.close()
        browser = await self._playwright.chromium.connect_over_cdp(self._config.cdp_url)
        context = browser.contexts[0]

        side_panel_url = create_side_panel_url(self._config, browser_window_id)
        side_panel_page, has_side_panel_target = await _find_side_panel_page_or_target(
            browser, side_panel_url
        )
        if side_panel_page is None:
            if not has_side_panel_target:
                raise NaradaTimeoutError("Timed out waiting for Narada side panel page")

        await self._fix_download_behavior(context, side_panel_page)

        if self._config.interactive:
            self._print_success_message(browser_window_id)

        self._playwright_browser = browser
        self._browser_process_id = None
        self._browser_window_id = browser_window_id
        self._context = context

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

            if browser_window_id is not None:
                side_panel_url = create_side_panel_url(config, browser_window_id)
                (
                    side_panel_page,
                    has_side_panel_target,
                ) = await _find_side_panel_page_or_target(browser, side_panel_url)
                if side_panel_page is not None or has_side_panel_target:
                    break

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
                await _BrowserInitializationHelper.install_browser_window_id_observer(
                    blank_page
                )
                await blank_page.goto(tagged_initialization_url)
                await proxy_cdp_session.detach()
                did_initial_navigation = True

            # Grab the browser window ID from the page we just opened.
            initialization_page = next(
                (p for p in context.pages if p.url == tagged_initialization_url), None
            )
            if initialization_page is not None:
                try:
                    browser_window_id = (
                        await self._wait_for_browser_window_id_with_lazy_login(
                            initialization_page,
                            config,
                            tagged_initialization_url,
                        )
                    )
                except NaradaTimeoutError:
                    if attempt == max_cdp_connect_attempts - 1:
                        raise

                    try:
                        await initialization_page.bring_to_front()
                        await initialization_page.goto(
                            tagged_initialization_url,
                            timeout=15_000,
                            wait_until="domcontentloaded",
                        )
                    except Exception:
                        pass

                    await browser.close()
                    await asyncio.sleep(3)
                    continue

                side_panel_url = create_side_panel_url(config, browser_window_id)
                (
                    side_panel_page,
                    has_side_panel_target,
                ) = await _find_side_panel_page_or_target(browser, side_panel_url)
                if side_panel_page is not None or has_side_panel_target:
                    break

            if attempt == max_cdp_connect_attempts - 1:
                if browser_window_id is not None:
                    raise NaradaTimeoutError(
                        "Timed out waiting for Narada side panel page"
                    )
                raise NaradaTimeoutError("Timed out waiting for initialization page")

            # Close the current CDP connection and try again.
            await browser.close()
            await asyncio.sleep(3)

        # These are impossible as we would've raised an exception above otherwise.
        assert browser_window_id is not None

        if config.interactive:
            self._print_success_message(browser_window_id)

        return _LaunchBrowserResult(
            playwright_browser=browser,
            browser_process_id=browser_process.pid,
            browser_window_id=browser_window_id,
            browser_context=context,
            side_panel_page=side_panel_page,
        )

    async def _fetch_browser_login_token(self) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self._base_url}/auth/custom-token",
                headers=self._auth_headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if not resp.ok:
                    error_text = await resp.text()
                    raise NaradaInitializationError(
                        "Failed to sign in the Narada browser with SDK credentials: "
                        f"{resp.status} {error_text}"
                    )

                return _CustomTokenResponse.model_validate(await resp.json()).token

    async def _wait_for_browser_window_id_with_lazy_login(
        self,
        initialization_page: Page,
        config: BrowserConfig,
        initialization_url: str,
        *,
        timeout: int = 30_000,
    ) -> str:
        login_attempts = 0
        max_login_attempts = 2

        try:
            while True:
                try:
                    return await _BrowserInitializationHelper.wait_for_browser_window_id_silently(
                        initialization_page,
                        timeout=timeout,
                    )
                except NaradaExtensionMissingError:
                    if not config.interactive:
                        raise

                    self._console.input(
                        "\n[bold]>[/bold] [bold blue]The Narada Enterprise extension is not "
                        "installed. Please follow the instructions in the browser window to "
                        "install it first, then press Enter to continue.[/bold blue]\n",
                    )
                    await initialization_page.bring_to_front()
                    await asyncio.sleep(0.1)
                    await initialization_page.reload()
                except NaradaExtensionUnauthenticatedError as error:
                    if login_attempts >= max_login_attempts:
                        raise NaradaExtensionUnauthenticatedError(
                            "Automatic sign-in with SDK credentials did not complete"
                        ) from error

                    login_attempts += 1
                    if config.interactive:
                        self._console.print(
                            "\n[bold]>[/bold] [bold blue]Signing in to Narada with your SDK "
                            "credentials...[/bold blue]\n",
                        )

                    custom_token = await self._fetch_browser_login_token()
                    await initialization_page.goto(
                        _with_query_params(
                            initialization_url,
                            {"customToken": custom_token},
                        ),
                        timeout=15_000,
                        wait_until="domcontentloaded",
                    )

        except PlaywrightError:
            self._console.print(
                "\n[bold]>[/bold] [bold red]It seems the Narada automation page was closed. Please "
                "retry the action and keep the Narada web page open.[/bold red]",
            )
            sys.exit(1)

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

    async def _fix_download_behavior(
        self,
        browser_context: BrowserContext,
        side_panel_page: Page | None,
    ) -> None:
        """Reverts the download behavior to the default behavior for the extension, otherwise our
        extension cannot download files.
        """
        if await self._try_fix_download_behavior_with_browser_cdp(browser_context):
            return

        if side_panel_page is None:
            raise NaradaInitializationError(
                "Failed to set download behavior because the Narada side panel is not "
                "available as a Playwright page and the browser-level CDP session is "
                "unavailable."
            )

        await self._fix_download_behavior_with_side_panel_page(side_panel_page)

    async def _try_fix_download_behavior_with_browser_cdp(
        self,
        browser_context: BrowserContext,
    ) -> bool:
        browser = browser_context.browser
        if browser is None:
            return False

        cdp_session: CDPSession | None = None
        try:
            cdp_session = await browser.new_browser_cdp_session()
            await cdp_session.send(
                "Browser.setDownloadBehavior", {"behavior": "default"}
            )
            return True
        except Exception:
            logger.debug(
                "Failed to set browser-level download behavior",
                exc_info=True,
            )
            return False
        finally:
            if cdp_session is not None:
                try:
                    await cdp_session.detach()
                except Exception:
                    pass

    async def _fix_download_behavior_with_side_panel_page(
        self,
        side_panel_page: Page,
    ) -> None:
        cdp_session = await side_panel_page.context.new_cdp_session(side_panel_page)
        try:
            await cdp_session.send("Page.setDownloadBehavior", {"behavior": "default"})
        finally:
            await cdp_session.detach()

    def _print_success_message(self, browser_window_id: str) -> None:
        self._browser_initialization.print_success_message(browser_window_id)


class RemoteBrowserEnvironment(BaseBrowserEnvironment):
    def __init__(
        self,
        *,
        browser_window_id: str,
        cloud_browser_session_id: str | None = None,
        api_key: str | None = None,
        auth_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            auth_headers=auth_headers,
            browser_window_id=browser_window_id,
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
        """Closes the remote browser environment.

        If this window is backed by a cloud browser session, this also stops the cloud
        session.
        """
        if self._cloud_browser_session_id is None:
            return await self._run_extension_action(
                CloseWindowRequest(), timeout=timeout
            )

        await _stop_cloud_browser_session(
            base_url=self._base_url,
            auth_headers=self._auth_headers,
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
            auth_headers=self._auth_headers,
            session_id=self._cloud_browser_session_id,
        )

    def __str__(self) -> str:
        return f"RemoteBrowserEnvironment(browser_window_id={self.browser_window_id})"


class CloudBrowserEnvironment(_PlaywrightLifecycleMixin, BaseBrowserEnvironment):
    """A browser environment that connects to a backend-cloud browser session via CDP.

    This class connects to a cloud browser session created by the backend API and provides
    the same transport semantics as other browser environments for agent operations.
    """

    _playwright_client_not_connected_message = "Cloud browser client is not connected"

    def __init__(
        self,
        *,
        config: BrowserConfig | None = None,
        session_name: str | None = None,
        session_timeout: int | None = None,
        api_key: str | None = None,
        auth_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            auth_headers=auth_headers,
        )
        self._config = config or BrowserConfig()
        self._session_name = session_name
        self._session_timeout = session_timeout
        self._session_id: str | None = None
        self._context: BrowserContext | None = None
        self._playwright_browser: Browser | None = None
        self._playwright_lifecycle_lock: asyncio.Lock | None = None
        self._cdp_websocket_url: str | None = None
        self._cdp_auth_headers: dict[str, str] | None = None
        self._playwright_context_manager: PlaywrightContextManager | None = None
        self._playwright: Playwright | None = None
        self._browser_initialization = _BrowserInitializationHelper(
            console=self._console
        )

    @property
    def cloud_browser_session_id(self) -> str:
        if self._session_id is None:
            raise RuntimeError(
                "Cloud browser environment is not initialized yet. Call `await env.start()` "
                "or run an agent action first."
            )
        return self._session_id

    @property
    def browser_process_id(self) -> int | None:
        # Cloud browser sessions are backend-owned, so there is no local browser process.
        return None

    async def _initialize(self) -> None:
        """Create a cloud browser session and initialize the browser extension.
        Retry up to 3 times on error.

        Calls ``POST /cloud-browser/create-cloud-browser-session``, then connects local
        Playwright over CDP, opens ``login_url``, and waits for
        ``#narada-browser-window-id`` (extension install retries apply). ``config`` controls
        interactive prompts and related behavior.
        """
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                await self._initialize_once()
                try:
                    await self._detach()
                except Exception:
                    logger.warning(
                        "Failed to detach Playwright resources after cloud browser initialization",
                        exc_info=True,
                    )
                return
            except Exception as error:
                await self._cleanup_failed_initialization_attempt()
                if (
                    attempt == max_attempts - 1
                    or self._is_non_retryable_initialization_error(error)
                ):
                    raise

                retry_backoff_with_jitter = 2 ** (attempt + 1) + random.uniform(0, 1)
                await asyncio.sleep(retry_backoff_with_jitter)

    async def _initialize_once(self) -> None:
        await self._start_playwright()
        request_body = {
            "require_extension": True,
            "session_name": self._session_name,
            "session_timeout": self._session_timeout,
        }
        endpoint_url = f"{self._base_url}/cloud-browser/create-cloud-browser-session"

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
                    err = RuntimeError(
                        f"Failed to create cloud browser session: {resp.status} {error_text}\n"
                        f"Endpoint URL: {endpoint_url}"
                    )
                    err.status_code = resp.status  # type: ignore[attr-defined]
                    if resp.status == HTTPStatus.FORBIDDEN:
                        error = ApiErrorPayload.from_error_text(error_text)
                        err.detail = error.detail  # type: ignore[attr-defined]
                    raise err
                response_data = await resp.json()

        cdp_websocket_url = response_data["cdp_websocket_url"]
        session_id = response_data["session_id"]
        login_url = response_data["login_url"]
        cdp_auth_headers = response_data["cdp_auth_headers"]
        self._session_id = session_id
        self._cdp_websocket_url = cdp_websocket_url
        self._cdp_auth_headers = cdp_auth_headers

        # Connect to browser via CDP with authentication headers and log the user in.
        await self._initialize_cloud_browser_window(
            cdp_websocket_url=cdp_websocket_url,
            session_id=session_id,
            login_url=login_url,
            cdp_auth_headers=cdp_auth_headers,
        )

    @staticmethod
    def _is_non_retryable_initialization_error(error: Exception) -> bool:
        status_code = getattr(error, "status_code", None)
        return isinstance(status_code, int) and 400 <= status_code < 500

    async def _cleanup_failed_initialization_attempt(self) -> None:
        if self._session_id is not None:
            try:
                await _stop_cloud_browser_session(
                    base_url=self._base_url,
                    auth_headers=self._auth_headers,
                    session_id=self._session_id,
                    status="failed",
                    timeout=10,
                )
            except Exception:
                logger.exception(
                    "Error cleaning up session %s (%s) after failed initialization",
                    self._session_id,
                    self._session_name,
                )

        try:
            await self._stop_playwright()
        except Exception:
            logger.exception(
                "Error stopping Playwright after failed cloud browser initialization"
            )
        finally:
            self._session_id = None
            self._browser_window_id = None
            self._context = None
            self._cdp_websocket_url = None
            self._cdp_auth_headers = None

    async def _connect_playwright_browser(self) -> Browser:
        if self._cdp_websocket_url is None or self._cdp_auth_headers is None:
            raise NaradaInitializationError(
                "Cloud browser CDP connection details are unavailable"
            )

        assert self._playwright is not None
        return await self._playwright.chromium.connect_over_cdp(
            self._cdp_websocket_url,
            headers=self._cdp_auth_headers,
        )

    async def _wait_for_cloud_browser_window_id(
        self,
        initialization_page: Page,
        config: BrowserConfig,
        timeout: int = 30_000,
    ) -> str:
        return await self._browser_initialization.wait_for_browser_window_id(
            initialization_page, config, timeout=timeout
        )

    def _print_success_message(self, browser_window_id: str) -> None:
        self._browser_initialization.print_success_message(browser_window_id)

    async def _initialize_cloud_browser_window(
        self,
        *,
        cdp_websocket_url: str,
        session_id: str,
        login_url: str,
        cdp_auth_headers: dict[str, str],
        expected_browser_window_id: str | None = None,
    ) -> None:
        assert self._playwright is not None

        # Connect to browser via CDP with authentication headers
        browser = await self._playwright.chromium.connect_over_cdp(
            cdp_websocket_url, headers=cdp_auth_headers
        )
        self._playwright_browser = browser

        # Navigate to login URL (provided by backend with custom token)
        context = browser.contexts[0]
        initialization_page = context.pages[0]
        if expected_browser_window_id is not None:
            # Put the backend-owned browser ID into sessionStorage before hydration
            # so AgentCore sessions use the right Firestore route when needed.
            expected_browser_window_id_json = json.dumps(expected_browser_window_id)
            await initialization_page.add_init_script(
                script=f"""
                    (() => {{
                      const expectedBrowserWindowId = {expected_browser_window_id_json};
                      try {{
                        sessionStorage.setItem(
                          "naradaBrowserWindowId",
                          expectedBrowserWindowId
                        );
                      }} catch (_error) {{}}
                    }})();
                """
            )
        await _BrowserInitializationHelper.install_browser_window_id_observer(
            initialization_page
        )
        await initialization_page.goto(
            login_url, timeout=15_000, wait_until="domcontentloaded"
        )

        # Wait for browser window ID. The extension can take a bit to be installed, so we retry a
        # few times.
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                browser_window_id = await self._wait_for_cloud_browser_window_id(
                    initialization_page,
                    self._config,
                    timeout=30_000,
                )
                break
            except NaradaExtensionMissingError:
                if attempt == max_attempts - 1:
                    raise
                logging.info("Waiting for Narada extension to be installed...")
                await asyncio.sleep(1)
            except (NaradaTimeoutError, NaradaExtensionUnauthenticatedError):
                if attempt == max_attempts - 1:
                    raise
                # If browser window ID is not found, reload the page and try again
                # try to go to the login URL again (with customToken query param)
                await initialization_page.goto(
                    login_url, timeout=15_000, wait_until="domcontentloaded"
                )

        if (
            expected_browser_window_id is not None
            and browser_window_id != expected_browser_window_id
        ):
            raise RuntimeError(
                "Initialized cloud session reported browserWindowId "
                f"{browser_window_id!r}, expected {expected_browser_window_id!r}."
            )

        self._browser_window_id = browser_window_id
        self._session_id = session_id
        self._context = context

        if self._config.interactive:
            self._print_success_message(browser_window_id)

    @override
    async def _close_impl(self, *, timeout: int | None = None) -> None:
        """Stops the cloud browser session.

        Unlike local browser windows where close() closes a single window, this stops the
        entire cloud session since the serverless container manages the browser lifecycle.
        """
        try:
            if self._session_id is not None:
                await _stop_cloud_browser_session(
                    base_url=self._base_url,
                    auth_headers=self._auth_headers,
                    session_id=self._session_id,
                    timeout=timeout,
                )
        finally:
            await self._detach()

    async def get_downloaded_files(self) -> list[SessionDownloadItem]:
        """Return files downloaded during this cloud browser session (file name, size, presigned GET URL per file)."""
        return await _get_cloud_browser_downloads(
            base_url=self._base_url,
            auth_headers=self._auth_headers,
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
    """Cloud execution environment without browser actions.

    This uses the same backend endpoint as the old extensionless cloud-browser path:
    ``POST /cloud-browser/create-and-initialize-cloud-browser-session``. The backend provisions
    and initializes the execution target server-side, so local Playwright is not used.
    """

    def __init__(
        self,
        *,
        session_name: str | None = None,
        session_timeout: int | None = None,
        api_key: str | None = None,
        auth_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(api_key=api_key, auth_headers=auth_headers)
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
        endpoint_url = f"{self._base_url}/cloud-browser/create-and-initialize-cloud-browser-session"
        request_body = {
            "require_extension": False,
            "session_name": self._session_name,
            "session_timeout": self._session_timeout,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint_url,
                headers=self._auth_headers,
                json=request_body,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if not resp.ok:
                    error_text = await resp.text()
                    if resp.status == HTTPStatus.FORBIDDEN:
                        error = ApiErrorPayload.from_error_text(error_text)
                        err = RuntimeError(
                            f"Failed to create lambda environment: {resp.status} {error_text}\n"
                            f"Endpoint URL: {endpoint_url}"
                        )
                        err.status_code = resp.status  # type: ignore[attr-defined]
                        err.detail = error.detail  # type: ignore[attr-defined]
                        raise err
                    raise RuntimeError(
                        f"Failed to create lambda environment: {resp.status} {error_text}\n"
                        f"Endpoint URL: {endpoint_url}"
                    )
                response_data = await resp.json()

        self._browser_window_id = response_data["browser_window_id"]
        self._session_id = response_data["session_id"]

    async def _close_impl(self, *, timeout: int | None = None) -> None:
        if self._session_id is None:
            return

        await _stop_cloud_browser_session(
            base_url=self._base_url,
            auth_headers=self._auth_headers,
            session_id=self._session_id,
            timeout=timeout,
        )

    async def get_downloaded_files(self) -> list[SessionDownloadItem]:
        """Return files downloaded during this lambda session (file name, size, presigned GET URL per file)."""
        return await _get_cloud_browser_downloads(
            base_url=self._base_url,
            auth_headers=self._auth_headers,
            session_id=self.session_id,
        )


async def _fetch_presigned_download_url(
    http_session: aiohttp.ClientSession,
    *,
    base_url: str,
    auth_headers: dict[str, str],
    session_id: str,
    key: str,
    timeout: aiohttp.ClientTimeout,
) -> str:
    async with http_session.get(
        f"{base_url}/cloud-browser/replay/download-url",
        params={"session_id": session_id, "key": key},
        headers=auth_headers,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data["presigned_url"]


async def _get_cloud_browser_downloads(
    *,
    base_url: str,
    auth_headers: dict[str, str],
    session_id: str,
) -> list[SessionDownloadItem]:
    """GET cloud-browser session downloads and return list of SessionDownloadItem with presigned URLs."""
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession() as http_session:
        async with http_session.get(
            f"{base_url}/cloud-browser/replay/downloads",
            params={"session_id": session_id},
            headers=auth_headers,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        files = data.get("downloaded_files") or []
        if not files:
            return []

        presigned_urls = await asyncio.gather(
            *[
                _fetch_presigned_download_url(
                    http_session,
                    base_url=base_url,
                    auth_headers=auth_headers,
                    session_id=session_id,
                    key=f["key"],
                    timeout=timeout,
                )
                for f in files
            ]
        )
    return [
        SessionDownloadItem(
            file_name=item["file_name"],
            size=item["size"],
            download_url=presigned_urls[i],
        )
        for i, item in enumerate(files)
    ]


async def _stop_cloud_browser_session(
    *,
    base_url: str,
    auth_headers: dict[str, str],
    session_id: str,
    status: Literal["complete", "terminated", "failed", "timed_out"] = "complete",
    timeout: int | None = None,
) -> None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/cloud-browser/stop-cloud-browser-session",
                headers=auth_headers,
                json={"session_id": session_id, "status": status},
                timeout=aiohttp.ClientTimeout(total=timeout or 40),
            ) as resp:
                if resp.ok:
                    response_data = await resp.json()
                    if not response_data.get("success"):
                        logger.warning(
                            "Failed to stop session: %s",
                            response_data.get("message"),
                        )
                else:
                    logger.warning("Failed to stop session: %s", resp.status)
    except Exception as e:
        logger.warning("Error calling stop session endpoint: %s", e)


def create_side_panel_url(config: BrowserConfig, browser_window_id: str) -> str:
    return f"chrome-extension://{config.extension_id}/sidepanel.html?browserWindowId={browser_window_id}"


def _find_page_by_url(browser: Browser, url: str) -> Page | None:
    for context in browser.contexts:
        for page in context.pages:
            if page.url == url:
                return page

    return None


async def _get_cdp_target_infos(browser: Browser) -> list[dict[str, Any]]:
    cdp_session = None
    try:
        cdp_session = await browser.new_browser_cdp_session()
        result = await cdp_session.send("Target.getTargets")
    except Exception:
        return []
    finally:
        if cdp_session is not None:
            try:
                await cdp_session.detach()
            except Exception:
                pass

    target_infos = result.get("targetInfos")
    if not isinstance(target_infos, list):
        return []

    return [
        target_info for target_info in target_infos if isinstance(target_info, dict)
    ]


async def _find_side_panel_page_or_target(
    browser: Browser, side_panel_url: str
) -> tuple[Page | None, bool]:
    side_panel_page = _find_page_by_url(browser, side_panel_url)
    if side_panel_page is not None:
        return side_panel_page, True

    return None, await _has_cdp_target_url(browser, side_panel_url)


async def _has_cdp_target_url(browser: Browser, url: str) -> bool:
    for target_info in await _get_cdp_target_infos(browser):
        if target_info.get("url") == url:
            return True

    return False

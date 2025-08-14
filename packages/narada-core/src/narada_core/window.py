"""Base browser window class with common functionality."""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Generic, Literal, TypeVar, overload

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
    RemoteDispatchChatHistoryItem,
    Response,
    UserResourceCredentials,
    _MaybeStructuredOutput,
    _ResponseModel,
    _StructuredOutput,
)
from pydantic import BaseModel


class BaseBrowserWindow(ABC):
    """Abstract base class for browser window implementations."""

    _browser_window_id: str

    def __init__(self, *, browser_window_id: str) -> None:
        self._browser_window_id = browser_window_id

    @property
    def browser_window_id(self) -> str:
        """The current browser window's globally unique ID."""
        return self._browser_window_id

    # Abstract methods that must be implemented by subclasses
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

    @abstractmethod
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
        """Low-level API for invoking an agent. Must be implemented by subclasses."""
        pass

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

    @abstractmethod
    async def _run_extension_action(
        self,
        request: ExtensionActionRequest,
        response_model: type[_ResponseModel] | None = None,
        *,
        timeout: int | None = None,
    ) -> _ResponseModel | None:
        """Run an extension action. Must be implemented by subclasses."""
        pass

    # Common methods that use the abstract methods
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
        """Invokes an agent in the Narada extension side panel chat."""
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

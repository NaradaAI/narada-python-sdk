from __future__ import annotations

from typing import IO, Any, Generic, Literal, Mapping, TypeVar, overload

from narada_core.actions.critic import merge_critic_workflow_trace, run_critic
from narada_core.actions.models import (
    DEFAULT_HITL_TIMEOUT_SECONDS,
    AgenticMatchingSelectorsFinderRequest,
    AgenticMatchingSelectorsFinderResponse,
    AgenticMouseAction,
    AgenticMouseActionRequest,
    AgenticSelectorAction,
    AgenticSelectorRequest,
    AgenticSelectorResponse,
    AgenticSelectors,
    AgentResponse,
    AgentUsage,
    CriticResult,
    ExecuteJavaScriptOnPageRequest,
    ExecuteJavaScriptOnPageResponse,
    GetFileRequest,
    GetFileResponse,
    GetFullHtmlRequest,
    GetFullHtmlResponse,
    GetScreenshotRequest,
    GetScreenshotResponse,
    GetSimplifiedHtmlRequest,
    GetSimplifiedHtmlResponse,
    GetUrlRequest,
    GetUrlResponse,
    GoToUrlRequest,
    JsonValue,
    PressKeyEventItem,
    PressKeyRequest,
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
from narada_core.models import (
    AgentKind,
    CriticConfig,
    File,
    McpServer,
    ReasoningEffort,
    RemoteDispatchChatHistoryItem,
    Response,
    UserResourceCredentials,
)
from narada_core.tracing.model import parse_action_trace
from pydantic import BaseModel

from narada.environment import (
    BaseBrowserEnvironment,
    Environment,
    InputRequiredCallback,
)

from . import _trace

_StructuredOutput = TypeVar("_StructuredOutput", bound=BaseModel)


class Agent(Generic[_StructuredOutput]):
    def __init__(
        self,
        *,
        environment: Environment,
        kind: AgentKind | str = AgentKind.OPERATOR,
    ) -> None:
        self.environment = environment
        self.kind = kind

    # `reasoning` is only valid with the Core Agent; these two overloads make
    # that constraint type-checkable when callers construct a core-agent instance.
    @overload
    async def run(
        self,
        prompt: str,
        *,
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
        critic: CriticConfig | None = None,
        timeout: int = 1000,
    ) -> AgentResponse[dict[str, Any]]: ...

    @overload
    async def run(
        self,
        prompt: str,
        *,
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
        critic: CriticConfig | None = None,
        timeout: int = 1000,
    ) -> AgentResponse[_StructuredOutput]: ...

    async def run(
        self,
        prompt: str,
        *,
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
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: Mapping[str, Any] | None = None,
        on_input_required: InputRequiredCallback | None = None,
        critic: CriticConfig | None = None,
        timeout: int = 1000,
    ) -> AgentResponse:
        """Invokes an agent in the bound Narada environment."""
        remote_dispatch_response = await self._dispatch_request(
            prompt=prompt,
            clear_chat=clear_chat,
            generate_gif=generate_gif,
            output_schema=output_schema,
            previous_request_id=previous_request_id,
            chat_history=chat_history,
            additional_context=additional_context,
            attachment=attachment,
            time_zone=time_zone,
            user_resource_credentials=user_resource_credentials,
            mcp_servers=mcp_servers,
            secret_variables=secret_variables,
            input_variables=input_variables,
            callback_url=callback_url,
            callback_secret=callback_secret,
            callback_headers=callback_headers,
            on_input_required=on_input_required,
            reasoning=reasoning,
            timeout=timeout,
        )
        response_content = remote_dispatch_response["response"]
        assert response_content is not None

        action_trace_raw = response_content.get("actionTrace")
        action_trace = (
            parse_action_trace(action_trace_raw)
            if action_trace_raw is not None
            else None
        )
        workflow_trace = response_content.get("workflowTrace")
        parent_request_id = self.environment._current_parent_request_id()

        critic_result: CriticResult | None = None
        if critic is not None:
            critic_result = await run_critic(
                dispatch_request=self._dispatch_request,
                original_prompt=prompt,
                response_content=response_content,
                action_trace_raw=action_trace_raw,
                critic=critic,
                time_zone=time_zone,
                timeout=timeout,
            )
            workflow_trace = merge_critic_workflow_trace(
                workflow_trace=workflow_trace,
                critic_result=critic_result,
            )

        # Preserve the response contract for direct callers, but avoid adding a second
        # child node when the backend will stitch the child request into the parent row.
        if workflow_trace is not None and parent_request_id is None:
            _trace.emit_sub_workflow(workflow_trace=workflow_trace)

        return AgentResponse(
            request_id=remote_dispatch_response["requestId"],
            status=remote_dispatch_response["status"],
            text=response_content["text"],
            output=response_content.get("output"),
            structured_output=response_content.get("structuredOutput"),
            usage=AgentUsage.model_validate(remote_dispatch_response["usage"]),
            action_trace=action_trace,
            workflow_trace=workflow_trace,
            critic_result=critic_result,
        )

    async def _dispatch_request(
        self,
        *,
        prompt: str,
        agent: AgentKind | str | None = None,
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
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: Mapping[str, Any] | None = None,
        on_input_required: InputRequiredCallback | None = None,
        critic_context: dict[str, Any] | None = None,
        timeout: int = 1000,
    ) -> Response:
        dispatch_agent = self.kind if agent is None else agent
        # Branch on `reasoning` so each call site binds a single, typed overload
        # of `_dispatch_request`. The validation also lives in `_dispatch_request`
        # itself (defense in depth + reachable when callers go straight to the
        # low-level API), so the redundancy here is intentional.
        if reasoning is None:
            remote_dispatch_response = await self.environment._dispatch_request(
                prompt=prompt,
                agent=dispatch_agent,
                clear_chat=clear_chat,
                generate_gif=generate_gif,
                output_schema=output_schema,
                previous_request_id=previous_request_id,
                chat_history=chat_history,
                additional_context=additional_context,
                attachment=attachment,
                time_zone=time_zone,
                user_resource_credentials=user_resource_credentials,
                mcp_servers=mcp_servers,
                secret_variables=secret_variables,
                input_variables=input_variables,
                callback_url=callback_url,
                callback_secret=callback_secret,
                callback_headers=callback_headers,
                on_input_required=on_input_required,
                critic_context=critic_context,
                timeout=timeout,
            )
        else:
            if dispatch_agent is not AgentKind.CORE_AGENT:
                raise ValueError(
                    "`reasoning` is only supported with `kind=AgentKind.CORE_AGENT` "
                    f"(got kind={dispatch_agent!r})"
                )
            # The CORE_AGENT-specific overloads of `_dispatch_request` split on
            # a narrower `output_schema` discriminator (None vs `type[T]`),
            # which the impl's `type[BaseModel] | None` union doesn't cleanly
            # narrow into without further branching. The public `run()`
            # overloads above already give callers correct return-type
            # narrowing, so the internal forward call bypasses overload
            # disambiguation on this single dimension.
            remote_dispatch_response = await self.environment._dispatch_request(  # pyright: ignore[reportCallIssue]
                prompt=prompt,
                agent=dispatch_agent,
                reasoning=reasoning,
                clear_chat=clear_chat,
                generate_gif=generate_gif,
                output_schema=output_schema,  # pyright: ignore[reportArgumentType]
                previous_request_id=previous_request_id,
                chat_history=chat_history,
                additional_context=additional_context,
                attachment=attachment,
                time_zone=time_zone,
                user_resource_credentials=user_resource_credentials,
                mcp_servers=mcp_servers,
                secret_variables=secret_variables,
                input_variables=input_variables,
                callback_url=callback_url,
                callback_secret=callback_secret,
                callback_headers=callback_headers,
                on_input_required=on_input_required,
                critic_context=critic_context,
                timeout=timeout,
            )
        return remote_dispatch_response

    def _browser_environment(self) -> BaseBrowserEnvironment:
        if not isinstance(self.environment, BaseBrowserEnvironment):
            raise ValueError(
                f"{type(self.environment).__name__} does not support browser actions"
            )
        return self.environment

    async def agentic_selector(
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

        result = await self._browser_environment()._run_extension_action(
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

    async def agentic_matching_selectors_finder(
        self,
        *,
        prompt: str,
        timeout: int | None = 300,
    ) -> list[AgenticSelectors]:
        """Finds all visible targets matching a prompt and returns selectors."""
        result = await self._browser_environment()._run_extension_action(
            AgenticMatchingSelectorsFinderRequest(prompt=prompt),
            AgenticMatchingSelectorsFinderResponse,
            timeout=timeout,
        )
        return result.selectors

    async def press_key(
        self,
        *,
        events: list[PressKeyEventItem | Mapping[str, Any]],
        timeout: int | None = 60,
    ) -> None:
        """Dispatch keyboard events on the active tab through the extension."""
        if not events:
            raise ValueError("press_key requires a non-empty events= list")

        normalized_events = [
            event
            if isinstance(event, PressKeyEventItem)
            else PressKeyEventItem.model_validate(event)
            for event in events
        ]
        return await self._browser_environment()._run_extension_action(
            PressKeyRequest(events=normalized_events),
            timeout=timeout,
        )

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
        return await self._browser_environment()._run_extension_action(
            AgenticMouseActionRequest(
                action=action,
                recorded_click=recorded_click,
                resize_window=resize_window,
                fallback_operator_query=fallback_operator_query,
            ),
            timeout=timeout,
        )

    async def go_to_url(
        self, *, url: str, new_tab: bool = False, timeout: int | None = None
    ) -> None:
        """Navigates the active page in this window to the given URL."""
        return await self._browser_environment()._run_extension_action(
            GoToUrlRequest(url=url, new_tab=new_tab), timeout=timeout
        )

    async def wait_for_element(
        self,
        *,
        selectors: AgenticSelectors,
        state: Literal["visible", "hidden"],
        timeout: int,
    ) -> bool:
        """Waits for an element matching the given selectors to reach the specified state.

        Returns True if the element was found, False if no selector matched before timeout.
        """
        result = await self._browser_environment()._run_extension_action(
            WaitForElementRequest(selectors=selectors, state=state, timeout=timeout),
            WaitForElementResponse,
            timeout=timeout // 1000 + 30,
        )
        if result is None:
            return False
        return result.found

    async def get_url(self, *, timeout: int | None = None) -> GetUrlResponse:
        """Gets the URL of the current active page."""
        result = await self._browser_environment()._run_extension_action(
            GetUrlRequest(),
            GetUrlResponse,
            timeout=timeout,
        )
        return result

    async def execute_javascript_on_page(
        self, *, code: str, timeout: int | None = None
    ) -> JsonValue:
        """Executes JavaScript on the current active page and returns its JSON result."""
        result = await self._browser_environment()._run_extension_action(
            ExecuteJavaScriptOnPageRequest(code=code),
            ExecuteJavaScriptOnPageResponse,
            timeout=timeout,
        )
        return result.result

    async def print_message(self, *, message: str, timeout: int | None = None) -> None:
        """Prints a message in the Narada extension side panel chat."""
        return await self._browser_environment()._run_extension_action(
            PrintMessageRequest(message=message), timeout=timeout
        )

    async def prompt_for_user_input(
        self,
        *,
        step_id: str,
        variables: list[PromptForUserInputVariable],
        prompt_message: str | None = None,
        timeout: int | None = DEFAULT_HITL_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Prompts the user for one or more input values in the extension UI."""
        result = await self._browser_environment()._run_extension_action(
            PromptForUserInputRequest(
                step_id=step_id, prompt_message=prompt_message, variables=variables
            ),
            PromptForUserInputResponse,
            timeout=timeout,
        )
        return result.values_by_name

    async def user_approval(
        self,
        *,
        step_id: str,
        prompt_message: str,
        approve_label: str,
        reject_label: str,
        timeout: int | None = DEFAULT_HITL_TIMEOUT_SECONDS,
    ) -> bool:
        """Prompts the user to approve or reject in the extension UI."""
        result = await self._browser_environment()._run_extension_action(
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

    async def read_google_sheet(
        self,
        *,
        spreadsheet_id: str,
        range: str,
        timeout: int | None = None,
    ) -> ReadGoogleSheetResponse:
        """Reads a range of cells from a Google Sheet."""
        return await self._browser_environment()._run_extension_action(
            ReadGoogleSheetRequest(spreadsheet_id=spreadsheet_id, range=range),
            ReadGoogleSheetResponse,
            timeout=timeout,
        )

    async def read_excel_sheet(
        self,
        *,
        workbook_url: str,
        range: str,
        microsoft_account_email: str,
        timeout: int | None = None,
    ) -> ReadExcelSheetResponse:
        """Reads a range of cells from a Microsoft Excel workbook."""
        return await self._browser_environment()._run_extension_action(
            ReadExcelSheetRequest(
                workbook_url=workbook_url,
                range=range,
                microsoft_account_email=microsoft_account_email,
            ),
            ReadExcelSheetResponse,
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
        return await self._browser_environment()._run_extension_action(
            WriteGoogleSheetRequest(
                spreadsheet_id=spreadsheet_id, range=range, values=values
            ),
            timeout=timeout,
        )

    async def write_excel_sheet(
        self,
        *,
        workbook_url: str,
        range: str,
        microsoft_account_email: str,
        values: list[list[str]],
        timeout: int | None = None,
    ) -> None:
        """Writes a range of cells to a Microsoft Excel workbook."""
        return await self._browser_environment()._run_extension_action(
            WriteExcelSheetRequest(
                workbook_url=workbook_url,
                range=range,
                microsoft_account_email=microsoft_account_email,
                values=values,
            ),
            timeout=timeout,
        )

    async def get_full_html(self, *, timeout: int | None = None) -> GetFullHtmlResponse:
        """Gets the full HTML content of the current page."""
        return await self._browser_environment()._run_extension_action(
            GetFullHtmlRequest(),
            GetFullHtmlResponse,
            timeout=timeout,
        )

    async def get_simplified_html(
        self, *, timeout: int | None = None
    ) -> GetSimplifiedHtmlResponse:
        """Gets the simplified HTML content of the current page."""
        return await self._browser_environment()._run_extension_action(
            GetSimplifiedHtmlRequest(),
            GetSimplifiedHtmlResponse,
            timeout=timeout,
        )

    async def get_file(self, *, timeout: int | None = None) -> GetFileResponse:
        """Gets the PDF file displayed in the current browser page."""
        return await self._browser_environment()._run_extension_action(
            GetFileRequest(),
            GetFileResponse,
            timeout=timeout,
        )

    async def get_screenshot(
        self, *, timeout: int | None = None
    ) -> GetScreenshotResponse:
        """Takes a screenshot of the current browser window."""
        return await self._browser_environment()._run_extension_action(
            GetScreenshotRequest(),
            GetScreenshotResponse,
            timeout=timeout,
        )

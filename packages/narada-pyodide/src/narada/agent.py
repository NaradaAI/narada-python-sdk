from __future__ import annotations

from typing import IO, Any, Generic, Literal, Mapping, TypeVar, overload

from narada_core.actions.critic import run_critic
from narada_core.actions.models import (
    DEFAULT_HITL_TIMEOUT_SECONDS,
    AgenticMouseAction,
    AgenticSelectorAction,
    AgenticSelectorResponse,
    AgenticSelectors,
    AgentResponse,
    AgentUsage,
    CriticResult,
    GetFullHtmlResponse,
    GetScreenshotResponse,
    GetSimplifiedHtmlResponse,
    GetUrlResponse,
    PromptForUserInputVariable,
    ReadExcelSheetResponse,
    ReadGoogleSheetResponse,
    RecordedClick,
)
from narada_core.models import (
    AgentKind,
    CriticConfig,
    File,
    McpServer,
    ReasoningEffort,
    RemoteDispatchChatHistoryItem,
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
        # Branch on `reasoning` so each call site binds a single, typed overload
        # of `_dispatch_request`. The validation also lives in `_dispatch_request`
        # itself (defense in depth + reachable when callers go straight to the
        # low-level API), so the redundancy here is intentional.
        if reasoning is None:
            remote_dispatch_response = await self.environment._dispatch_request(
                prompt=prompt,
                agent=self.kind,
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
                timeout=timeout,
            )
        else:
            if self.kind is not AgentKind.CORE_AGENT:
                raise ValueError(
                    "`reasoning` is only supported with `kind=AgentKind.CORE_AGENT` "
                    f"(got kind={self.kind!r})"
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
                agent=self.kind,
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
        # Preserve the response contract for direct callers, but avoid adding a second
        # child node when the backend will stitch the child request into the parent row.
        if workflow_trace is not None and parent_request_id is None:
            _trace.emit_sub_workflow(workflow_trace=workflow_trace)

        critic_result: CriticResult | None = None
        if critic is not None:
            critic_result = await run_critic(
                dispatch_request=self.environment._dispatch_request,
                original_prompt=prompt,
                response_content=response_content,
                action_trace_raw=action_trace_raw,
                critic=critic,
                time_zone=time_zone,
                timeout=timeout,
            )

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
        timeout: int | None = 300,
    ) -> AgenticSelectorResponse:
        return await self._browser_environment()._agentic_selector(
            action=action,
            selectors=selectors,
            fallback_operator_query=fallback_operator_query,
            timeout=timeout,
        )

    async def agentic_matching_selectors_finder(
        self,
        *,
        prompt: str,
        timeout: int | None = 300,
    ) -> list[AgenticSelectors]:
        return await self._browser_environment()._agentic_matching_selectors_finder(
            prompt=prompt,
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
        return await self._browser_environment()._agentic_mouse_action(
            action=action,
            recorded_click=recorded_click,
            resize_window=resize_window,
            fallback_operator_query=fallback_operator_query,
            timeout=timeout,
        )

    async def go_to_url(
        self, *, url: str, new_tab: bool = False, timeout: int | None = None
    ) -> None:
        return await self._browser_environment()._go_to_url(
            url=url, new_tab=new_tab, timeout=timeout
        )

    async def wait_for_element(
        self,
        *,
        selectors: AgenticSelectors,
        state: Literal["visible", "hidden"],
        timeout: int,
    ) -> bool:
        return await self._browser_environment()._wait_for_element(
            selectors=selectors,
            state=state,
            timeout=timeout,
        )

    async def get_url(self, *, timeout: int | None = None) -> GetUrlResponse:
        return await self._browser_environment()._get_url(timeout=timeout)

    async def print_message(self, *, message: str, timeout: int | None = None) -> None:
        return await self._browser_environment()._print_message(
            message=message,
            timeout=timeout,
        )

    async def prompt_for_user_input(
        self,
        *,
        step_id: str,
        variables: list[PromptForUserInputVariable],
        prompt_message: str | None = None,
        timeout: int | None = DEFAULT_HITL_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        return await self._browser_environment()._prompt_for_user_input(
            step_id=step_id,
            variables=variables,
            prompt_message=prompt_message,
            timeout=timeout,
        )

    async def user_approval(
        self,
        *,
        step_id: str,
        prompt_message: str,
        approve_label: str,
        reject_label: str,
        timeout: int | None = DEFAULT_HITL_TIMEOUT_SECONDS,
    ) -> bool:
        return await self._browser_environment()._user_approval(
            step_id=step_id,
            prompt_message=prompt_message,
            approve_label=approve_label,
            reject_label=reject_label,
            timeout=timeout,
        )

    async def read_google_sheet(
        self,
        *,
        spreadsheet_id: str,
        range: str,
        timeout: int | None = None,
    ) -> ReadGoogleSheetResponse:
        return await self._browser_environment()._read_google_sheet(
            spreadsheet_id=spreadsheet_id,
            range=range,
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
        return await self._browser_environment()._read_excel_sheet(
            workbook_url=workbook_url,
            range=range,
            microsoft_account_email=microsoft_account_email,
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
        return await self._browser_environment()._write_google_sheet(
            spreadsheet_id=spreadsheet_id,
            range=range,
            values=values,
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
        return await self._browser_environment()._write_excel_sheet(
            workbook_url=workbook_url,
            range=range,
            microsoft_account_email=microsoft_account_email,
            values=values,
            timeout=timeout,
        )

    async def get_full_html(self, *, timeout: int | None = None) -> GetFullHtmlResponse:
        return await self._browser_environment()._get_full_html(timeout=timeout)

    async def get_simplified_html(
        self, *, timeout: int | None = None
    ) -> GetSimplifiedHtmlResponse:
        return await self._browser_environment()._get_simplified_html(timeout=timeout)

    async def get_screenshot(
        self, *, timeout: int | None = None
    ) -> GetScreenshotResponse:
        return await self._browser_environment()._get_screenshot(timeout=timeout)

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
type SpanStatus = Literal[
    "running",
    "success",
    "error",
    "aborted",
    "input_required",
    "skipped",
    "timeout",
    "unknown",
]


class _OmitNoneModel(BaseModel):
    @model_serializer(mode="wrap")
    def _serialize_without_none(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> Any:
        serialized = handler(self)
        if not isinstance(serialized, dict):
            return serialized
        return {key: value for key, value in serialized.items() if value is not None}


class TraceMetadata(BaseModel):
    schema_version: Literal["1"] = "1"


class Trace(BaseModel):
    object: Literal["trace"] = "trace"
    id: str
    workflow_name: str
    group_id: str | None = None
    metadata: TraceMetadata = Field(default_factory=TraceMetadata)


class SpanError(_OmitNoneModel):
    message: str
    data: dict[str, JsonValue] | None = None


class SpanData(_OmitNoneModel):
    type: str


class WorkflowSpanData(SpanData):
    type: Literal["workflow"] = "workflow"
    name: str
    workflow_id: str
    workflow_run_id: str | None = None
    status: SpanStatus
    request_id: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    output_names: list[str] | None = None
    outcome: Literal["completed", "end_tree"] | None = None


class RemoteWorkflowRunLink(_OmitNoneModel):
    workflow_id: str
    workflow_name: str
    invocation_index: NonNegativeInt | None = None
    request_id: str | None = None
    status: Literal["success", "error", "aborted", "skipped"]
    error_summary: str | None = None


class GuiStepSpanDataBase(SpanData):
    type: str
    name: str | None = None
    step_id: str
    status: SpanStatus
    description: str | None = None
    page_url: str | None = None


class AgentStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.agent"] = "gui_step.agent"
    selected_agent_type: str


class AgenticMouseActionStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.agentic_mouse_action"] = "gui_step.agentic_mouse_action"
    strategy: Literal["direct", "operator_fallback"]
    verification_status: bool | None = None
    verification_status_variable_name: str | None = None


class AgenticSelectorStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.agentic_selector"] = "gui_step.agentic_selector"
    strategy: Literal["selector", "operator_fallback"]


class RunBashScriptStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.run_bash_script"] = "gui_step.run_bash_script"


class BreakStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.break"] = "gui_step.break"


class CloseTabStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.close_tab"] = "gui_step.close_tab"


class ContinueStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.continue"] = "gui_step.continue"


class DataTableExportAsCsvStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.data_table_export_as_csv"] = (
        "gui_step.data_table_export_as_csv"
    )


class DataTableInsertRowStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.data_table_insert_row"] = "gui_step.data_table_insert_row"


class DataTableUpdateCellValueStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.data_table_update_cell_value"] = (
        "gui_step.data_table_update_cell_value"
    )


class DesktopAgenticSelectorStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.desktop_agentic_selector"] = (
        "gui_step.desktop_agentic_selector"
    )


class ExecuteJavaScriptOnPageStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.execute_javascript_on_page"] = (
        "gui_step.execute_javascript_on_page"
    )


class OpenDesktopApplicationStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.open_desktop_application"] = (
        "gui_step.open_desktop_application"
    )


class ReadLocalFilesystemStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.read_local_filesystem"] = "gui_step.read_local_filesystem"


class WriteLocalFilesystemStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.write_local_filesystem"] = "gui_step.write_local_filesystem"


class EndStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.end"] = "gui_step.end"
    outcome: Literal["end", "end_tree"]
    result_status: Literal["success", "error"] | None = None
    message: str | None = None


class ForStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.for"] = "gui_step.for"
    loop_type: Literal[
        "n_times",
        "for_each_table_row",
        "for_each_array_item",
    ]
    total_iterations: NonNegativeInt


class SavePdfFileStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.save_pdf_file"] = "gui_step.save_pdf_file"


class GetFullHtmlStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.get_full_html"] = "gui_step.get_full_html"


class GetScreenshotStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.get_screenshot"] = "gui_step.get_screenshot"


class GetSimplifiedHtmlStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.get_simplified_html"] = "gui_step.get_simplified_html"


class GetUrlStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.get_url"] = "gui_step.get_url"
    observed_url: str | None = None


class NavigateStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.navigate"] = "gui_step.navigate"
    destination_url: str | None = None
    final_url: str | None = None


class HttpRequestStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.http_request"] = "gui_step.http_request"
    method: str | None = None
    destination_host: str | None = None
    status_code: NonNegativeInt | None = None


class IfStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.if"] = "gui_step.if"
    condition_summary: str | None = None
    selected_branch_role: Literal["then", "else_if", "else"] | None = None
    selected_branch_index: NonNegativeInt | None = None


class LogVariablesToFileStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.log_variables_to_file"] = "gui_step.log_variables_to_file"


class ObjectExportAsJsonStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.object_export_as_json"] = "gui_step.object_export_as_json"


class ObjectSetPropertiesStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.object_set_properties"] = "gui_step.object_set_properties"


class PressKeysStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.press_keys"] = "gui_step.press_keys"


class PrintStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.print"] = "gui_step.print"
    message: str | None = None


class ProjectExecutableStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.project_executable"] = "gui_step.project_executable"
    project_relative_path: str | None = None


class ExecutePythonStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.execute_python"] = "gui_step.execute_python"


class ReadCsvStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.read_csv"] = "gui_step.read_csv"


class ReadExcelSheetStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.read_excel_sheet"] = "gui_step.read_excel_sheet"


class ReadGoogleSheetStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.read_google_sheet"] = "gui_step.read_google_sheet"


class EmailActionStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.email_action"] = "gui_step.email_action"
    provider_status: str | None = None


class SlackActionStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.slack_action"] = "gui_step.slack_action"
    provider_status: str | None = None


class SetVariableStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.set_variable"] = "gui_step.set_variable"
    variable_name: str | None = None


class PromptForUserInputStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.prompt_for_user_input"] = "gui_step.prompt_for_user_input"


class StartStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.start"] = "gui_step.start"


class ThrowStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.throw"] = "gui_step.throw"


class TryCatchStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.try_catch"] = "gui_step.try_catch"
    caught_error: bool | None = None
    executed_catch: bool | None = None
    executed_finally: bool | None = None


class UserApprovalStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.user_approval"] = "gui_step.user_approval"


class WaitStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.wait"] = "gui_step.wait"
    duration_ms: NonNegativeInt | None = None


class WaitForElementStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.wait_for_element"] = "gui_step.wait_for_element"


class WhileStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.while"] = "gui_step.while"
    condition_summary: str | None = None
    total_iterations: NonNegativeInt


class WriteExcelSheetStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.write_excel_sheet"] = "gui_step.write_excel_sheet"


class WriteGoogleSheetStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.write_google_sheet"] = "gui_step.write_google_sheet"


class RunCustomAgentStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.run_custom_agent"] = "gui_step.run_custom_agent"
    workflow_id: str
    workflow_name: str
    remote_run: RemoteWorkflowRunLink | None = None


class RunCustomAgentsInParallelStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.run_custom_agents_in_parallel"] = (
        "gui_step.run_custom_agents_in_parallel"
    )
    runs: list[RemoteWorkflowRunLink]


class RunCustomAgentForEachStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.run_custom_agent_for_each"] = (
        "gui_step.run_custom_agent_for_each"
    )
    workflow_id: str
    workflow_name: str
    total_items: NonNegativeInt
    runs: list[RemoteWorkflowRunLink]


class OutputStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.output"] = "gui_step.output"
    output_names: list[str] | None = None


class CriticAgentStepData(GuiStepSpanDataBase):
    type: Literal["gui_step.critic_agent"] = "gui_step.critic_agent"
    prompt_summary: str | None = None


type GuiStepSpanData = Annotated[
    AgentStepData
    | AgenticMouseActionStepData
    | AgenticSelectorStepData
    | RunBashScriptStepData
    | BreakStepData
    | CloseTabStepData
    | ContinueStepData
    | DataTableExportAsCsvStepData
    | DataTableInsertRowStepData
    | DataTableUpdateCellValueStepData
    | DesktopAgenticSelectorStepData
    | ExecuteJavaScriptOnPageStepData
    | OpenDesktopApplicationStepData
    | ReadLocalFilesystemStepData
    | WriteLocalFilesystemStepData
    | EndStepData
    | ForStepData
    | SavePdfFileStepData
    | GetFullHtmlStepData
    | GetScreenshotStepData
    | GetSimplifiedHtmlStepData
    | GetUrlStepData
    | NavigateStepData
    | HttpRequestStepData
    | IfStepData
    | LogVariablesToFileStepData
    | ObjectExportAsJsonStepData
    | ObjectSetPropertiesStepData
    | PressKeysStepData
    | PrintStepData
    | ProjectExecutableStepData
    | ExecutePythonStepData
    | ReadCsvStepData
    | ReadExcelSheetStepData
    | ReadGoogleSheetStepData
    | EmailActionStepData
    | SlackActionStepData
    | SetVariableStepData
    | PromptForUserInputStepData
    | StartStepData
    | ThrowStepData
    | TryCatchStepData
    | UserApprovalStepData
    | WaitStepData
    | WaitForElementStepData
    | WhileStepData
    | WriteExcelSheetStepData
    | WriteGoogleSheetStepData
    | RunCustomAgentStepData
    | RunCustomAgentsInParallelStepData
    | RunCustomAgentForEachStepData
    | OutputStepData
    | CriticAgentStepData,
    Field(discriminator="type"),
]


class ControlFlowSpanDataBase(SpanData):
    type: str
    status: SpanStatus


class IterationSpanData(ControlFlowSpanDataBase):
    type: Literal["control_flow.iteration"] = "control_flow.iteration"


class TrySpanData(ControlFlowSpanDataBase):
    type: Literal["control_flow.try"] = "control_flow.try"


class CatchSpanData(ControlFlowSpanDataBase):
    type: Literal["control_flow.catch"] = "control_flow.catch"


class FinallySpanData(ControlFlowSpanDataBase):
    type: Literal["control_flow.finally"] = "control_flow.finally"


type ControlFlowSpanData = Annotated[
    IterationSpanData | TrySpanData | CatchSpanData | FinallySpanData,
    Field(discriminator="type"),
]


class UsageData(_OmitNoneModel):
    actions: NonNegativeInt
    credits: NonNegativeFloat
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    total_tokens: NonNegativeInt | None = None


class AgentSpanDataBase(SpanData):
    type: str
    name: str
    handoffs: list[str] | None = None
    tools: list[str] | None = None
    output_type: str | None = None
    status: SpanStatus
    agent_id: str | None = None
    request_id: str | None = None
    page_url: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    usage: UsageData | None = None

    @model_serializer(mode="wrap")
    def _serialize_agent_data(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> Any:
        serialized = handler(self)
        if not isinstance(serialized, dict):
            return serialized
        nullable_openai_fields = {"handoffs", "tools", "output_type"}
        return {
            key: value
            for key, value in serialized.items()
            if value is not None or key in nullable_openai_fields
        }


class OperatorAgentSpanData(AgentSpanDataBase):
    type: Literal["agent.operator"] = "agent.operator"


class CoreAgentSpanData(AgentSpanDataBase):
    type: Literal["agent.core"] = "agent.core"


class ProductivityAgentSpanData(AgentSpanDataBase):
    type: Literal["agent.productivity"] = "agent.productivity"


class CustomAgentSpanData(AgentSpanDataBase):
    type: Literal["agent.custom"] = "agent.custom"


class CriticAgentSpanData(AgentSpanDataBase):
    type: Literal["agent.critic"] = "agent.critic"


class OtherAgentSpanData(AgentSpanDataBase):
    type: Literal["agent.other"] = "agent.other"
    agent_kind: str


type AgentSpanData = Annotated[
    OperatorAgentSpanData
    | CoreAgentSpanData
    | ProductivityAgentSpanData
    | CustomAgentSpanData
    | CriticAgentSpanData
    | OtherAgentSpanData,
    Field(discriminator="type"),
]


class AgentActionSpanData(SpanData):
    type: Literal["agent_action"] = "agent_action"
    name: str
    message: str
    status: SpanStatus
    url: str | None = None
    credits: NonNegativeFloat | None = None


type SpanDataUnion = Annotated[
    WorkflowSpanData
    | GuiStepSpanData
    | ControlFlowSpanData
    | AgentSpanData
    | AgentActionSpanData,
    Field(discriminator="type"),
]


class Span(BaseModel):
    object: Literal["trace.span"] = "trace.span"
    id: str
    trace_id: str
    parent_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    span_data: SpanDataUnion
    error: SpanError | None = None

    @field_validator("started_at", "ended_at")
    @classmethod
    def _require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() != timedelta(0):
            raise ValueError("trace timestamps must be timezone-aware UTC datetimes")
        return value

    @model_validator(mode="after")
    def _validate_timestamp_order(self) -> Span:
        if (
            self.started_at is not None
            and self.ended_at is not None
            and self.ended_at < self.started_at
        ):
            raise ValueError("ended_at must be greater than or equal to started_at")
        return self


type TraceRecord = Annotated[Trace | Span, Field(discriminator="object")]


__all__ = [
    "AgentActionSpanData",
    "AgenticMouseActionStepData",
    "AgenticSelectorStepData",
    "AgentSpanData",
    "AgentSpanDataBase",
    "AgentStepData",
    "BreakStepData",
    "CatchSpanData",
    "CloseTabStepData",
    "ContinueStepData",
    "ControlFlowSpanData",
    "ControlFlowSpanDataBase",
    "CoreAgentSpanData",
    "CriticAgentSpanData",
    "CriticAgentStepData",
    "CustomAgentSpanData",
    "DataTableExportAsCsvStepData",
    "DataTableInsertRowStepData",
    "DataTableUpdateCellValueStepData",
    "DesktopAgenticSelectorStepData",
    "EmailActionStepData",
    "EndStepData",
    "ExecuteJavaScriptOnPageStepData",
    "ExecutePythonStepData",
    "FinallySpanData",
    "ForStepData",
    "GetFullHtmlStepData",
    "GetScreenshotStepData",
    "GetSimplifiedHtmlStepData",
    "GetUrlStepData",
    "GuiStepSpanData",
    "GuiStepSpanDataBase",
    "HttpRequestStepData",
    "IfStepData",
    "IterationSpanData",
    "JsonValue",
    "LogVariablesToFileStepData",
    "NavigateStepData",
    "ObjectExportAsJsonStepData",
    "ObjectSetPropertiesStepData",
    "OpenDesktopApplicationStepData",
    "OperatorAgentSpanData",
    "OtherAgentSpanData",
    "OutputStepData",
    "PressKeysStepData",
    "PrintStepData",
    "ProductivityAgentSpanData",
    "ProjectExecutableStepData",
    "PromptForUserInputStepData",
    "ReadCsvStepData",
    "ReadExcelSheetStepData",
    "ReadGoogleSheetStepData",
    "ReadLocalFilesystemStepData",
    "RemoteWorkflowRunLink",
    "RunBashScriptStepData",
    "RunCustomAgentForEachStepData",
    "RunCustomAgentStepData",
    "RunCustomAgentsInParallelStepData",
    "SavePdfFileStepData",
    "SetVariableStepData",
    "SlackActionStepData",
    "Span",
    "SpanData",
    "SpanDataUnion",
    "SpanError",
    "SpanStatus",
    "StartStepData",
    "ThrowStepData",
    "Trace",
    "TraceMetadata",
    "TraceRecord",
    "TryCatchStepData",
    "TrySpanData",
    "UsageData",
    "UserApprovalStepData",
    "WaitForElementStepData",
    "WaitStepData",
    "WhileStepData",
    "WorkflowSpanData",
    "WriteExcelSheetStepData",
    "WriteGoogleSheetStepData",
    "WriteLocalFilesystemStepData",
]

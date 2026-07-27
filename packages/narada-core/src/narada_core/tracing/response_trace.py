from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    field_validator,
    model_validator,
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
type WorkflowSpanStatus = Literal[
    "pending",
    "input-required",
    "success",
    "error",
    "expired",
]
type GuiStepSpanStatus = Literal["success", "error", "aborted", "end_tree"]
type AgentSpanStatus = Literal[
    "success",
    "error",
    "aborted",
    "input-required",
    "timeout",
]


class Trace(BaseModel):
    object: Literal["trace"] = Field(
        default="trace",
        description="Discriminator identifying this record as a trace.",
    )
    id: str = Field(description="Unique identifier for the trace.")
    group_id: str | None = Field(
        default=None,
        description="Optional identifier used to correlate related traces.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional trace-level metadata. Narada-owned metadata uses "
            "schema_version to identify the response trace schema."
        ),
    )


class SpanError(BaseModel):
    message: str = Field(description="Human-readable description of the span error.")
    data: dict[str, JsonValue] | None = Field(
        default=None,
        description="Optional structured details associated with the error.",
    )


class SpanData(BaseModel):
    type: str = Field(description="Discriminator for the span-specific payload.")


class WorkflowSpanData(SpanData):
    type: Literal["workflow"] = Field(
        default="workflow",
        description="Identifies a workflow execution span.",
    )
    workflow_name: str = Field(
        description="Display name of the workflow that executed."
    )
    workflow_id: str = Field(
        description="Stable identifier of the workflow definition that executed."
    )
    status: WorkflowSpanStatus = Field(
        description="Execution status stored for the remote workflow dispatch."
    )
    request_id: str | None = Field(
        default=None,
        description=(
            "Remote-dispatch request identifier for this workflow run. It is also "
            "the identifier used to look up the run."
        ),
    )
    output_variables: dict[str, Any] | None = Field(
        default=None,
        description="Runtime output variables produced by the workflow, when available.",
    )


class BaseGuiStepSpanData(SpanData):
    type: str = Field(description="Discriminator for the executed GUI step type.")
    name: str | None = Field(
        default=None,
        description="Optional user-facing label for the executed step.",
    )
    step_id: str = Field(
        description="Identifier of the step in the workflow definition."
    )
    status: GuiStepSpanStatus = Field(
        description="Terminal execution status reported for the GUI step."
    )
    description: str | None = Field(
        default=None,
        description="User-facing description produced while the step executed.",
    )
    page_url_before: str | None = Field(
        default=None,
        description="Browser page URL captured immediately before the step started.",
    )


class AgentStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.agent"] = Field(
        default="gui_step.agent",
        description="Identifies a GUI agent step.",
    )


class AgenticMouseActionStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.agentic_mouse_action"] = Field(
        default="gui_step.agentic_mouse_action",
        description="Identifies a GUI agentic mouse action step.",
    )
    strategy: Literal["direct", "operator_fallback"] = Field(
        description="Execution path that ultimately performed the mouse action."
    )
    verification_status: bool | None = Field(
        default=None,
        description=(
            "Whether post-action verification succeeded. This is absent when "
            "verification did not run."
        ),
    )


class AgenticSelectorStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.agentic_selector"] = Field(
        default="gui_step.agentic_selector",
        description="Identifies a GUI agentic selector step.",
    )
    strategy: Literal["selector", "operator_fallback"] = Field(
        description="Execution path that ultimately selected the element."
    )


class RunBashScriptStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.run_bash_script"] = Field(
        default="gui_step.run_bash_script",
        description="Identifies a GUI run-Bash-script step.",
    )


class BreakStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.break"] = Field(
        default="gui_step.break",
        description="Identifies a GUI break step.",
    )


class CloseTabStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.close_tab"] = Field(
        default="gui_step.close_tab",
        description="Identifies a GUI close-tab step.",
    )


class ContinueStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.continue"] = Field(
        default="gui_step.continue",
        description="Identifies a GUI continue step.",
    )


class DataTableExportAsCsvStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.data_table_export_as_csv"] = Field(
        default="gui_step.data_table_export_as_csv",
        description="Identifies a GUI data-table CSV export step.",
    )


class DataTableInsertRowStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.data_table_insert_row"] = Field(
        default="gui_step.data_table_insert_row",
        description="Identifies a GUI data-table row insertion step.",
    )


class DataTableUpdateCellValueStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.data_table_update_cell_value"] = Field(
        default="gui_step.data_table_update_cell_value",
        description="Identifies a GUI data-table cell update step.",
    )


class DesktopAgenticSelectorStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.desktop_agentic_selector"] = Field(
        default="gui_step.desktop_agentic_selector",
        description="Identifies a GUI desktop agentic selector step.",
    )


class ExecuteJavaScriptOnPageStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.execute_javascript_on_page"] = Field(
        default="gui_step.execute_javascript_on_page",
        description="Identifies a GUI in-page JavaScript execution step.",
    )


class OpenDesktopApplicationStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.open_desktop_application"] = Field(
        default="gui_step.open_desktop_application",
        description="Identifies a GUI open-desktop-application step.",
    )


class ReadLocalFilesystemStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.read_local_filesystem"] = Field(
        default="gui_step.read_local_filesystem",
        description="Identifies a GUI local-filesystem read step.",
    )


class WriteLocalFilesystemStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.write_local_filesystem"] = Field(
        default="gui_step.write_local_filesystem",
        description="Identifies a GUI local-filesystem write step.",
    )


class EndStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.end"] = Field(
        default="gui_step.end",
        description="Identifies a GUI end step.",
    )
    result_status: Literal["success", "error"] | None = Field(
        default=None,
        description="Workflow result selected by the executed end step, when provided.",
    )
    message: str | None = Field(
        default=None,
        description="Runtime message produced by the end step, when provided.",
    )


class ForStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.for"] = Field(
        default="gui_step.for",
        description="Identifies a GUI for-loop step.",
    )
    total_iterations: NonNegativeInt = Field(
        description="Number of loop iterations that started during this execution."
    )


class SavePdfFileStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.save_pdf_file"] = Field(
        default="gui_step.save_pdf_file",
        description="Identifies a GUI save-PDF-file step.",
    )


class GetFullHtmlStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.get_full_html"] = Field(
        default="gui_step.get_full_html",
        description="Identifies a GUI full-HTML retrieval step.",
    )


class GetScreenshotStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.get_screenshot"] = Field(
        default="gui_step.get_screenshot",
        description="Identifies a GUI screenshot step.",
    )


class GetSimplifiedHtmlStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.get_simplified_html"] = Field(
        default="gui_step.get_simplified_html",
        description="Identifies a GUI simplified-HTML retrieval step.",
    )


class GetUrlStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.get_url"] = Field(
        default="gui_step.get_url",
        description="Identifies a GUI get-URL step.",
    )
    url: str | None = Field(
        default=None,
        description="URL returned by the step during execution.",
    )


class NavigateStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.navigate"] = Field(
        default="gui_step.navigate",
        description="Identifies a GUI navigation step.",
    )
    final_url: str | None = Field(
        default=None,
        description="Browser URL observed after navigation completed.",
    )


class HttpRequestStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.http_request"] = Field(
        default="gui_step.http_request",
        description="Identifies a GUI HTTP-request step.",
    )
    status_code: NonNegativeInt | None = Field(
        default=None,
        description="HTTP response status code observed at runtime.",
    )


class IfStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.if"] = Field(
        default="gui_step.if",
        description="Identifies a GUI conditional step.",
    )
    selected_branch_role: Literal["then", "else_if", "else"] | None = Field(
        default=None,
        description="Role of the branch selected during execution.",
    )
    selected_branch_index: NonNegativeInt | None = Field(
        default=None,
        description=(
            "Zero-based index of the selected branch among branches with the "
            "reported role. It is absent when no branch ran."
        ),
    )


class LogVariablesToFileStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.log_variables_to_file"] = Field(
        default="gui_step.log_variables_to_file",
        description="Identifies a GUI variable-log file step.",
    )


class ObjectExportAsJsonStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.object_export_as_json"] = Field(
        default="gui_step.object_export_as_json",
        description="Identifies a GUI object JSON export step.",
    )


class ObjectSetPropertiesStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.object_set_properties"] = Field(
        default="gui_step.object_set_properties",
        description="Identifies a GUI object-property update step.",
    )


class PressKeysStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.press_keys"] = Field(
        default="gui_step.press_keys",
        description="Identifies a GUI key-press step.",
    )


class PrintStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.print"] = Field(
        default="gui_step.print",
        description="Identifies a GUI print step.",
    )
    message: str | None = Field(
        default=None,
        description="Rendered message emitted by the step during execution.",
    )


class ProjectExecutableStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.project_executable"] = Field(
        default="gui_step.project_executable",
        description="Identifies a GUI project-executable step.",
    )


class ExecutePythonStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.execute_python"] = Field(
        default="gui_step.execute_python",
        description="Identifies a GUI Python execution step.",
    )


class ReadCsvStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.read_csv"] = Field(
        default="gui_step.read_csv",
        description="Identifies a GUI CSV-read step.",
    )


class ReadExcelSheetStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.read_excel_sheet"] = Field(
        default="gui_step.read_excel_sheet",
        description="Identifies a GUI Excel-sheet read step.",
    )


class ReadGoogleSheetStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.read_google_sheet"] = Field(
        default="gui_step.read_google_sheet",
        description="Identifies a GUI Google-Sheet read step.",
    )


class EmailActionStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.email_action"] = Field(
        default="gui_step.email_action",
        description="Identifies a GUI email action step.",
    )
    provider_status: str | None = Field(
        default=None,
        description="Status returned by the email provider, when available.",
    )


class SlackActionStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.slack_action"] = Field(
        default="gui_step.slack_action",
        description="Identifies a GUI Slack action step.",
    )
    provider_status: str | None = Field(
        default=None,
        description="Status returned by Slack, when available.",
    )


class SetVariableStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.set_variable"] = Field(
        default="gui_step.set_variable",
        description="Identifies a GUI set-variable step.",
    )


class PromptForUserInputStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.prompt_for_user_input"] = Field(
        default="gui_step.prompt_for_user_input",
        description="Identifies a GUI user-input prompt step.",
    )


class StartStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.start"] = Field(
        default="gui_step.start",
        description="Identifies a GUI start step.",
    )


class ThrowStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.throw"] = Field(
        default="gui_step.throw",
        description="Identifies a GUI throw step.",
    )


class TryCatchStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.try_catch"] = Field(
        default="gui_step.try_catch",
        description="Identifies a GUI try/catch step.",
    )
    caught_error: bool = Field(
        description="Whether the try section produced an error that was caught."
    )
    executed_catch: bool = Field(description="Whether the catch section executed.")
    executed_finally: bool = Field(description="Whether the finally section executed.")


class UserApprovalStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.user_approval"] = Field(
        default="gui_step.user_approval",
        description="Identifies a GUI user-approval step.",
    )


class WaitStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.wait"] = Field(
        default="gui_step.wait",
        description="Identifies a GUI wait step.",
    )


class WaitForElementStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.wait_for_element"] = Field(
        default="gui_step.wait_for_element",
        description="Identifies a GUI wait-for-element step.",
    )


class WhileStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.while"] = Field(
        default="gui_step.while",
        description="Identifies a GUI while-loop step.",
    )
    total_iterations: NonNegativeInt = Field(
        description="Number of loop iterations that started during this execution."
    )


class WriteExcelSheetStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.write_excel_sheet"] = Field(
        default="gui_step.write_excel_sheet",
        description="Identifies a GUI Excel-sheet write step.",
    )


class WriteGoogleSheetStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.write_google_sheet"] = Field(
        default="gui_step.write_google_sheet",
        description="Identifies a GUI Google-Sheet write step.",
    )


class RunCustomAgentStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.run_custom_agent"] = Field(
        default="gui_step.run_custom_agent",
        description="Identifies a GUI custom-agent step.",
    )


class RunCustomAgentsInParallelStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.run_custom_agents_in_parallel"] = Field(
        default="gui_step.run_custom_agents_in_parallel",
        description="Identifies a GUI parallel custom-agent step.",
    )


class RunCustomAgentForEachStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.run_custom_agent_for_each"] = Field(
        default="gui_step.run_custom_agent_for_each",
        description="Identifies a GUI custom-agent-for-each step.",
    )
    total_items: NonNegativeInt = Field(
        description="Number of input items encountered during execution."
    )


class OutputStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.output"] = Field(
        default="gui_step.output",
        description="Identifies a GUI output step.",
    )
    output_variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Runtime variable values emitted by the output step.",
    )


class CriticAgentStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.critic_agent"] = Field(
        default="gui_step.critic_agent",
        description="Identifies a GUI critic-agent step.",
    )


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


class BaseControlFlowSpanData(SpanData):
    type: str = Field(description="Discriminator for the control-flow scope.")


class IterationSpanData(BaseControlFlowSpanData):
    type: Literal["control_flow.iteration"] = Field(
        default="control_flow.iteration",
        description="Identifies one executed loop iteration.",
    )
    iteration_index: NonNegativeInt = Field(
        description="Zero-based position of this iteration in the loop execution."
    )


class TrySpanData(BaseControlFlowSpanData):
    type: Literal["control_flow.try"] = Field(
        default="control_flow.try",
        description="Identifies an executed try section.",
    )


class CatchSpanData(BaseControlFlowSpanData):
    type: Literal["control_flow.catch"] = Field(
        default="control_flow.catch",
        description="Identifies an executed catch section.",
    )


class FinallySpanData(BaseControlFlowSpanData):
    type: Literal["control_flow.finally"] = Field(
        default="control_flow.finally",
        description="Identifies an executed finally section.",
    )


type ControlFlowSpanData = Annotated[
    IterationSpanData | TrySpanData | CatchSpanData | FinallySpanData,
    Field(discriminator="type"),
]


class UsageData(BaseModel):
    actions: NonNegativeInt = Field(
        description=(
            "Aggregate number of billable agent actions recorded for this run. "
            "This may differ from the number of returned action spans."
        )
    )
    credits: NonNegativeFloat = Field(
        description="Aggregate credits consumed by the agent run."
    )


class BaseAgentSpanData(SpanData):
    type: str = Field(description="Discriminator for the executed agent type.")
    name: str = Field(description="Display name of the agent that executed.")
    output_variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured output variables produced by the agent run.",
    )
    status: AgentSpanStatus = Field(
        description="Terminal status reported for the agent run."
    )
    request_id: str | None = Field(
        default=None,
        description="Request identifier associated with the agent run, when available.",
    )
    usage: UsageData | None = Field(
        default=None,
        description="Aggregate billable usage recorded for the agent run.",
    )


class OperatorAgentSpanData(BaseAgentSpanData):
    type: Literal["agent.operator"] = Field(
        default="agent.operator",
        description="Identifies an Operator agent run.",
    )


class CoreAgentSpanData(BaseAgentSpanData):
    type: Literal["agent.core"] = Field(
        default="agent.core",
        description="Identifies a Core agent run.",
    )


class ProductivityAgentSpanData(BaseAgentSpanData):
    type: Literal["agent.productivity"] = Field(
        default="agent.productivity",
        description="Identifies a Productivity agent run.",
    )


class CustomAgentSpanData(BaseAgentSpanData):
    type: Literal["agent.custom"] = Field(
        default="agent.custom",
        description="Identifies a custom agent run.",
    )


class CriticAgentSpanData(BaseAgentSpanData):
    type: Literal["agent.critic"] = Field(
        default="agent.critic",
        description="Identifies a critic agent run.",
    )


class OtherAgentSpanData(BaseAgentSpanData):
    type: Literal["agent.other"] = Field(
        default="agent.other",
        description="Identifies an agent run outside Narada's known agent types.",
    )
    agent_kind: str = Field(
        description="Runtime agent-kind value when no specific subtype is available."
    )


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
    type: Literal["agent_action"] = Field(
        default="agent_action",
        description="Identifies one user-facing action performed by an agent.",
    )
    name: str = Field(
        description="Short user-facing name for the action that executed."
    )
    message: str = Field(description="User-facing description of what the agent did.")
    url: str | None = Field(
        default=None,
        description="Browser page URL associated with the action, when available.",
    )
    credits: NonNegativeFloat | None = Field(
        default=None,
        description="Credits attributed to this individual action, when available.",
    )


type SpanDataUnion = Annotated[
    WorkflowSpanData
    | GuiStepSpanData
    | ControlFlowSpanData
    | AgentSpanData
    | AgentActionSpanData,
    Field(discriminator="type"),
]


class Span(BaseModel):
    object: Literal["trace.span"] = Field(
        default="trace.span",
        description="Discriminator identifying this record as a span.",
    )
    id: str = Field(description="Unique identifier for the span.")
    trace_id: str = Field(description="Identifier of the trace containing this span.")
    parent_id: str | None = Field(
        default=None,
        description="Identifier of the parent span, or null for a root span.",
    )
    started_at: datetime | None = Field(
        default=None,
        description="UTC ISO 8601 timestamp at which the span started.",
    )
    ended_at: datetime | None = Field(
        default=None,
        description="UTC ISO 8601 timestamp at which the span ended.",
    )
    span_data: SpanDataUnion = Field(
        description="Typed payload describing the operation represented by the span."
    )
    error: SpanError | None = Field(
        default=None,
        description="Error recorded for the span, or null when no error was recorded.",
    )

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


type TraceItem = Annotated[Trace | Span, Field(discriminator="object")]


__all__ = [
    "AgentActionSpanData",
    "AgenticMouseActionStepData",
    "AgenticSelectorStepData",
    "AgentSpanData",
    "AgentSpanStatus",
    "AgentStepData",
    "BaseAgentSpanData",
    "BaseControlFlowSpanData",
    "BaseGuiStepSpanData",
    "BreakStepData",
    "CatchSpanData",
    "CloseTabStepData",
    "ContinueStepData",
    "ControlFlowSpanData",
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
    "GuiStepSpanStatus",
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
    "StartStepData",
    "ThrowStepData",
    "Trace",
    "TraceItem",
    "TryCatchStepData",
    "TrySpanData",
    "UsageData",
    "UserApprovalStepData",
    "WaitForElementStepData",
    "WaitStepData",
    "WhileStepData",
    "WorkflowSpanData",
    "WorkflowSpanStatus",
    "WriteExcelSheetStepData",
    "WriteGoogleSheetStepData",
    "WriteLocalFilesystemStepData",
]

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
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
    "input-required",
]
type AgentType = Literal[
    "operator",
    "generalist",
    "coreAgent",
    "jira",
    "googleDrive",
    "gmail",
    "googleCalendar",
    "concur",
]


class Trace(BaseModel):
    object: Literal["trace"] = Field(
        default="trace",
        description="Discriminator identifying this record as a trace.",
    )
    trace_id: str = Field(
        description="Unique identifier for the trace.",
    )
    name: str = Field(
        description="Human-readable name of the logical workflow.",
    )
    group_id: str | None = Field(
        default=None,
        description="Optional identifier used to correlate related traces.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional user-provided metadata associated with the trace.",
    )


class SpanError(BaseModel):
    message: str = Field(description="Human-readable description of the span error.")
    data: dict[str, Any] | None = Field(
        description="Structured details associated with the error, or null.",
    )


class SpanData(BaseModel):
    type: str = Field(description="Discriminator for the span-specific payload.")


TSpanData = TypeVar("TSpanData", bound=SpanData)


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
    step_number: PositiveInt | None = Field(
        default=None,
        description=(
            "One-based display position of the step in the authored workflow, "
            "including steps nested inside control flow."
        ),
    )
    status: GuiStepSpanStatus = Field(
        description="Terminal execution status reported for the GUI step."
    )
    description: str | None = Field(
        default=None,
        description="User-facing description produced while the step executed.",
    )
    starting_url: str | None = Field(
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


class GoToUrlStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.go_to_url"] = Field(
        default="gui_step.go_to_url",
        description="Identifies a GUI go-to-URL step.",
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
    selected_condition: str | None = Field(
        default=None,
        description=(
            "Authored condition for the selected branch, with variable references "
            "left unevaluated. It is null when an else branch ran or no branch ran."
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


class NaradaCodeProjectExecutableStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.narada_code_project_executable"] = Field(
        default="gui_step.narada_code_project_executable",
        description="Identifies a GUI Narada Code project-executable step.",
    )


class PythonStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.python"] = Field(
        default="gui_step.python",
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
    caught_condition: str | None = Field(
        default=None,
        description=(
            "Authored condition for the first matching catch branch, with variable "
            "references left unevaluated. It is null when no error was caught."
        ),
    )


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
        description=(
            "Identifies a GUI custom-agent step. A successful execution parents "
            "the workflow span for the invoked workflow."
        ),
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
    | GoToUrlStepData
    | HttpRequestStepData
    | IfStepData
    | LogVariablesToFileStepData
    | ObjectExportAsJsonStepData
    | ObjectSetPropertiesStepData
    | PressKeysStepData
    | PrintStepData
    | NaradaCodeProjectExecutableStepData
    | PythonStepData
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


class AgentSpanData(SpanData):
    type: Literal["agent"] = Field(
        default="agent",
        description="Identifies an agent span, matching OpenAI's agent span type.",
    )
    name: str = Field(description="Display name of the agent that executed.")
    agent_type: AgentType = Field(
        description="Narada agent type selected for this execution."
    )
    output_variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured output variables produced by the agent run.",
    )
    response: Any | None = Field(
        default=None,
        description=(
            "Final response returned by the agent. Text responses are strings; "
            "structured responses contain their parsed JSON-compatible value."
        ),
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


class Span(BaseModel, Generic[TSpanData]):
    """A trace span that preserves the concrete type of its span data.

    The type parameter lets callers retain precise access to subtype-specific
    fields, for example ``Span[AgentSpanData].span_data.agent_type``. A
    discriminated union remains available separately for parsing serialized
    span data whose subtype is not known in advance.
    """

    object: Literal["trace.span"] = Field(
        default="trace.span",
        description="Discriminator identifying this record as a span.",
    )
    span_id: str = Field(
        description="Unique identifier for the span.",
    )
    trace_id: str = Field(description="Identifier of the trace containing this span.")
    parent_id: str | None = Field(
        default=None,
        description="Identifier of the parent span, or null for a root span.",
    )
    started_at: str | None = Field(
        default=None,
        description="UTC ISO 8601 timestamp at which the span started.",
    )
    ended_at: str | None = Field(
        default=None,
        description="UTC ISO 8601 timestamp at which the span ended.",
    )
    span_data: TSpanData = Field(
        description="Typed payload describing the operation represented by the span."
    )
    error: SpanError | None = Field(
        default=None,
        description="Error recorded for the span, or null when no error was recorded.",
    )

    @field_validator("started_at", "ended_at")
    @classmethod
    def _require_utc_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("trace timestamps must be ISO 8601 strings") from error
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("trace timestamps must be timezone-aware UTC datetimes")
        return value

    @model_validator(mode="after")
    def _validate_timestamp_order(self) -> Span:
        if (
            self.started_at is not None
            and self.ended_at is not None
            and datetime.fromisoformat(self.ended_at)
            < datetime.fromisoformat(self.started_at)
        ):
            raise ValueError("ended_at must be greater than or equal to started_at")
        return self


__all__ = [
    "AgentActionSpanData",
    "AgenticMouseActionStepData",
    "AgenticSelectorStepData",
    "AgentSpanData",
    "AgentSpanStatus",
    "AgentType",
    "AgentStepData",
    "BaseControlFlowSpanData",
    "BaseGuiStepSpanData",
    "BreakStepData",
    "CatchSpanData",
    "CloseTabStepData",
    "ContinueStepData",
    "ControlFlowSpanData",
    "CriticAgentStepData",
    "DataTableExportAsCsvStepData",
    "DataTableInsertRowStepData",
    "DataTableUpdateCellValueStepData",
    "DesktopAgenticSelectorStepData",
    "EmailActionStepData",
    "EndStepData",
    "ExecuteJavaScriptOnPageStepData",
    "FinallySpanData",
    "ForStepData",
    "GetFullHtmlStepData",
    "GetScreenshotStepData",
    "GetSimplifiedHtmlStepData",
    "GetUrlStepData",
    "GoToUrlStepData",
    "GuiStepSpanData",
    "GuiStepSpanStatus",
    "HttpRequestStepData",
    "IfStepData",
    "IterationSpanData",
    "LogVariablesToFileStepData",
    "NaradaCodeProjectExecutableStepData",
    "ObjectExportAsJsonStepData",
    "ObjectSetPropertiesStepData",
    "OpenDesktopApplicationStepData",
    "OutputStepData",
    "PressKeysStepData",
    "PrintStepData",
    "PromptForUserInputStepData",
    "PythonStepData",
    "ReadCsvStepData",
    "ReadExcelSheetStepData",
    "ReadGoogleSheetStepData",
    "ReadLocalFilesystemStepData",
    "RunBashScriptStepData",
    "RunCustomAgentStepData",
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

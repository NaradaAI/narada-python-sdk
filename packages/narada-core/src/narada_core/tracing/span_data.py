from __future__ import annotations

from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)

from narada_core.tracing.step_span_inputs import (
    AgenticMouseActionStepSpanInput,
    AgenticSelectorStepSpanInput,
    AgentStepSpanInput,
    AgentType,
    BreakStepSpanInput,
    CloseTabStepSpanInput,
    ContinueStepSpanInput,
    CriticAgentStepSpanInput,
    DataTableExportAsCsvStepSpanInput,
    DataTableInsertRowStepSpanInput,
    DataTableUpdateCellValueStepSpanInput,
    DesktopAgenticSelectorStepSpanInput,
    EmailActionStepSpanInput,
    EndStepSpanInput,
    ExecuteJavaScriptOnPageStepSpanInput,
    ForStepSpanInput,
    GetFullHtmlStepSpanInput,
    GetScreenshotStepSpanInput,
    GetSimplifiedHtmlStepSpanInput,
    GetUrlStepSpanInput,
    GoToUrlStepSpanInput,
    GuiStepSpanInput,
    HttpRequestStepSpanInput,
    IfStepSpanInput,
    LogVariablesToFileStepSpanInput,
    NaradaCodeProjectExecutableStepSpanInput,
    ObjectExportAsJsonStepSpanInput,
    ObjectSetPropertiesStepSpanInput,
    OpenDesktopApplicationStepSpanInput,
    OutputStepSpanInput,
    PressKeysStepSpanInput,
    PrintStepSpanInput,
    PromptForUserInputStepSpanInput,
    PythonStepSpanInput,
    ReadCsvStepSpanInput,
    ReadExcelSheetStepSpanInput,
    ReadGoogleSheetStepSpanInput,
    ReadLocalFilesystemStepSpanInput,
    RunBashScriptStepSpanInput,
    RunCustomAgentStepSpanInput,
    SavePdfFileStepSpanInput,
    SetVariableStepSpanInput,
    SlackActionStepSpanInput,
    StartStepSpanInput,
    ThrowStepSpanInput,
    TryCatchStepSpanInput,
    UserApprovalStepSpanInput,
    WaitForElementStepSpanInput,
    WaitStepSpanInput,
    WhileStepSpanInput,
    WriteExcelSheetStepSpanInput,
    WriteGoogleSheetStepSpanInput,
    WriteLocalFilesystemStepSpanInput,
)

type WorkflowSpanStatus = Literal[
    "pending",
    "input-required",
    "success",
    "error",
    "expired",
]
type GuiStepSpanStatus = Literal["success", "error", "aborted"]
type AgentSpanStatus = Literal[
    "success",
    "error",
    "input-required",
]


class SpanData(BaseModel):
    type: str = Field(description="Discriminator for the span-specific payload.")


TGuiStepSpanInput = TypeVar("TGuiStepSpanInput", bound=GuiStepSpanInput)


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


class BaseGuiStepSpanData(SpanData, Generic[TGuiStepSpanInput]):
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
    input: TGuiStepSpanInput | None = Field(
        default=None,
        description=(
            "Trace-safe snapshot of the effective input used by this step, when "
            "available."
        ),
    )
    output_variables: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Workflow variable names and runtime values written by this step execution."
        ),
    )


class AgentStepData(BaseGuiStepSpanData[AgentStepSpanInput]):
    type: Literal["gui_step.agent"] = Field(
        default="gui_step.agent",
        description="Identifies a GUI agent step.",
    )


class AgenticMouseActionStepData(BaseGuiStepSpanData[AgenticMouseActionStepSpanInput]):
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


class AgenticSelectorStepData(BaseGuiStepSpanData[AgenticSelectorStepSpanInput]):
    type: Literal["gui_step.agentic_selector"] = Field(
        default="gui_step.agentic_selector",
        description="Identifies a GUI agentic selector step.",
    )
    strategy: Literal["selector", "operator_fallback"] = Field(
        description="Execution path that ultimately selected the element."
    )


class RunBashScriptStepData(BaseGuiStepSpanData[RunBashScriptStepSpanInput]):
    type: Literal["gui_step.run_bash_script"] = Field(
        default="gui_step.run_bash_script",
        description="Identifies a GUI run-Bash-script step.",
    )


class BreakStepData(BaseGuiStepSpanData[BreakStepSpanInput]):
    type: Literal["gui_step.break"] = Field(
        default="gui_step.break",
        description="Identifies a GUI break step.",
    )


class CloseTabStepData(BaseGuiStepSpanData[CloseTabStepSpanInput]):
    type: Literal["gui_step.close_tab"] = Field(
        default="gui_step.close_tab",
        description="Identifies a GUI close-tab step.",
    )


class ContinueStepData(BaseGuiStepSpanData[ContinueStepSpanInput]):
    type: Literal["gui_step.continue"] = Field(
        default="gui_step.continue",
        description="Identifies a GUI continue step.",
    )


class DataTableExportAsCsvStepData(
    BaseGuiStepSpanData[DataTableExportAsCsvStepSpanInput]
):
    type: Literal["gui_step.data_table_export_as_csv"] = Field(
        default="gui_step.data_table_export_as_csv",
        description="Identifies a GUI data-table CSV export step.",
    )


class DataTableInsertRowStepData(BaseGuiStepSpanData[DataTableInsertRowStepSpanInput]):
    type: Literal["gui_step.data_table_insert_row"] = Field(
        default="gui_step.data_table_insert_row",
        description="Identifies a GUI data-table row insertion step.",
    )


class DataTableUpdateCellValueStepData(
    BaseGuiStepSpanData[DataTableUpdateCellValueStepSpanInput]
):
    type: Literal["gui_step.data_table_update_cell_value"] = Field(
        default="gui_step.data_table_update_cell_value",
        description="Identifies a GUI data-table cell update step.",
    )


class DesktopAgenticSelectorStepData(
    BaseGuiStepSpanData[DesktopAgenticSelectorStepSpanInput]
):
    type: Literal["gui_step.desktop_agentic_selector"] = Field(
        default="gui_step.desktop_agentic_selector",
        description="Identifies a GUI desktop agentic selector step.",
    )


class ExecuteJavaScriptOnPageStepData(
    BaseGuiStepSpanData[ExecuteJavaScriptOnPageStepSpanInput]
):
    type: Literal["gui_step.execute_javascript_on_page"] = Field(
        default="gui_step.execute_javascript_on_page",
        description="Identifies a GUI in-page JavaScript execution step.",
    )


class OpenDesktopApplicationStepData(
    BaseGuiStepSpanData[OpenDesktopApplicationStepSpanInput]
):
    type: Literal["gui_step.open_desktop_application"] = Field(
        default="gui_step.open_desktop_application",
        description="Identifies a GUI open-desktop-application step.",
    )


class ReadLocalFilesystemStepData(
    BaseGuiStepSpanData[ReadLocalFilesystemStepSpanInput]
):
    type: Literal["gui_step.read_local_filesystem"] = Field(
        default="gui_step.read_local_filesystem",
        description="Identifies a GUI local-filesystem read step.",
    )


class WriteLocalFilesystemStepData(
    BaseGuiStepSpanData[WriteLocalFilesystemStepSpanInput]
):
    type: Literal["gui_step.write_local_filesystem"] = Field(
        default="gui_step.write_local_filesystem",
        description="Identifies a GUI local-filesystem write step.",
    )


class EndStepData(BaseGuiStepSpanData[EndStepSpanInput]):
    type: Literal["gui_step.end"] = Field(
        default="gui_step.end",
        description="Identifies a GUI end step.",
    )


class ForStepData(BaseGuiStepSpanData[ForStepSpanInput]):
    type: Literal["gui_step.for"] = Field(
        default="gui_step.for",
        description="Identifies a GUI for-loop step.",
    )


class SavePdfFileStepData(BaseGuiStepSpanData[SavePdfFileStepSpanInput]):
    type: Literal["gui_step.save_pdf_file"] = Field(
        default="gui_step.save_pdf_file",
        description="Identifies a GUI save-PDF-file step.",
    )


class GetFullHtmlStepData(BaseGuiStepSpanData[GetFullHtmlStepSpanInput]):
    type: Literal["gui_step.get_full_html"] = Field(
        default="gui_step.get_full_html",
        description="Identifies a GUI full-HTML retrieval step.",
    )


class GetScreenshotStepData(BaseGuiStepSpanData[GetScreenshotStepSpanInput]):
    type: Literal["gui_step.get_screenshot"] = Field(
        default="gui_step.get_screenshot",
        description="Identifies a GUI screenshot step.",
    )


class GetSimplifiedHtmlStepData(BaseGuiStepSpanData[GetSimplifiedHtmlStepSpanInput]):
    type: Literal["gui_step.get_simplified_html"] = Field(
        default="gui_step.get_simplified_html",
        description="Identifies a GUI simplified-HTML retrieval step.",
    )


class GetUrlStepData(BaseGuiStepSpanData[GetUrlStepSpanInput]):
    type: Literal["gui_step.get_url"] = Field(
        default="gui_step.get_url",
        description="Identifies a GUI get-URL step.",
    )


class GoToUrlStepData(BaseGuiStepSpanData[GoToUrlStepSpanInput]):
    type: Literal["gui_step.go_to_url"] = Field(
        default="gui_step.go_to_url",
        description="Identifies a GUI go-to-URL step.",
    )


class HttpRequestStepData(BaseGuiStepSpanData[HttpRequestStepSpanInput]):
    type: Literal["gui_step.http_request"] = Field(
        default="gui_step.http_request",
        description="Identifies a GUI HTTP-request step.",
    )


class IfStepData(BaseGuiStepSpanData[IfStepSpanInput]):
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


class LogVariablesToFileStepData(BaseGuiStepSpanData[LogVariablesToFileStepSpanInput]):
    type: Literal["gui_step.log_variables_to_file"] = Field(
        default="gui_step.log_variables_to_file",
        description="Identifies a GUI variable-log file step.",
    )


class ObjectExportAsJsonStepData(BaseGuiStepSpanData[ObjectExportAsJsonStepSpanInput]):
    type: Literal["gui_step.object_export_as_json"] = Field(
        default="gui_step.object_export_as_json",
        description="Identifies a GUI object JSON export step.",
    )


class ObjectSetPropertiesStepData(
    BaseGuiStepSpanData[ObjectSetPropertiesStepSpanInput]
):
    type: Literal["gui_step.object_set_properties"] = Field(
        default="gui_step.object_set_properties",
        description="Identifies a GUI object-property update step.",
    )


class PressKeysStepData(BaseGuiStepSpanData[PressKeysStepSpanInput]):
    type: Literal["gui_step.press_keys"] = Field(
        default="gui_step.press_keys",
        description="Identifies a GUI key-press step.",
    )


class PrintStepData(BaseGuiStepSpanData[PrintStepSpanInput]):
    type: Literal["gui_step.print"] = Field(
        default="gui_step.print",
        description="Identifies a GUI print step.",
    )


class NaradaCodeProjectExecutableStepData(
    BaseGuiStepSpanData[NaradaCodeProjectExecutableStepSpanInput]
):
    type: Literal["gui_step.narada_code_project_executable"] = Field(
        default="gui_step.narada_code_project_executable",
        description="Identifies a GUI Narada Code project-executable step.",
    )


class PythonStepData(BaseGuiStepSpanData[PythonStepSpanInput]):
    type: Literal["gui_step.python"] = Field(
        default="gui_step.python",
        description="Identifies a GUI Python execution step.",
    )


class ReadCsvStepData(BaseGuiStepSpanData[ReadCsvStepSpanInput]):
    type: Literal["gui_step.read_csv"] = Field(
        default="gui_step.read_csv",
        description="Identifies a GUI CSV-read step.",
    )


class ReadExcelSheetStepData(BaseGuiStepSpanData[ReadExcelSheetStepSpanInput]):
    type: Literal["gui_step.read_excel_sheet"] = Field(
        default="gui_step.read_excel_sheet",
        description="Identifies a GUI Excel-sheet read step.",
    )


class ReadGoogleSheetStepData(BaseGuiStepSpanData[ReadGoogleSheetStepSpanInput]):
    type: Literal["gui_step.read_google_sheet"] = Field(
        default="gui_step.read_google_sheet",
        description="Identifies a GUI Google-Sheet read step.",
    )


class EmailActionStepData(BaseGuiStepSpanData[EmailActionStepSpanInput]):
    type: Literal["gui_step.email_action"] = Field(
        default="gui_step.email_action",
        description="Identifies a GUI email action step.",
    )


class SlackActionStepData(BaseGuiStepSpanData[SlackActionStepSpanInput]):
    type: Literal["gui_step.slack_action"] = Field(
        default="gui_step.slack_action",
        description="Identifies a GUI Slack action step.",
    )


class SetVariableStepData(BaseGuiStepSpanData[SetVariableStepSpanInput]):
    type: Literal["gui_step.set_variable"] = Field(
        default="gui_step.set_variable",
        description="Identifies a GUI set-variable step.",
    )


class PromptForUserInputStepData(BaseGuiStepSpanData[PromptForUserInputStepSpanInput]):
    type: Literal["gui_step.prompt_for_user_input"] = Field(
        default="gui_step.prompt_for_user_input",
        description="Identifies a GUI user-input prompt step.",
    )


class StartStepData(BaseGuiStepSpanData[StartStepSpanInput]):
    type: Literal["gui_step.start"] = Field(
        default="gui_step.start",
        description="Identifies a GUI start step.",
    )


class ThrowStepData(BaseGuiStepSpanData[ThrowStepSpanInput]):
    type: Literal["gui_step.throw"] = Field(
        default="gui_step.throw",
        description="Identifies a GUI throw step.",
    )


class TryCatchStepData(BaseGuiStepSpanData[TryCatchStepSpanInput]):
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


class UserApprovalStepData(BaseGuiStepSpanData[UserApprovalStepSpanInput]):
    type: Literal["gui_step.user_approval"] = Field(
        default="gui_step.user_approval",
        description="Identifies a GUI user-approval step.",
    )


class WaitStepData(BaseGuiStepSpanData[WaitStepSpanInput]):
    type: Literal["gui_step.wait"] = Field(
        default="gui_step.wait",
        description="Identifies a GUI wait step.",
    )


class WaitForElementStepData(BaseGuiStepSpanData[WaitForElementStepSpanInput]):
    type: Literal["gui_step.wait_for_element"] = Field(
        default="gui_step.wait_for_element",
        description="Identifies a GUI wait-for-element step.",
    )


class WhileStepData(BaseGuiStepSpanData[WhileStepSpanInput]):
    type: Literal["gui_step.while"] = Field(
        default="gui_step.while",
        description="Identifies a GUI while-loop step.",
    )


class WriteExcelSheetStepData(BaseGuiStepSpanData[WriteExcelSheetStepSpanInput]):
    type: Literal["gui_step.write_excel_sheet"] = Field(
        default="gui_step.write_excel_sheet",
        description="Identifies a GUI Excel-sheet write step.",
    )


class WriteGoogleSheetStepData(BaseGuiStepSpanData[WriteGoogleSheetStepSpanInput]):
    type: Literal["gui_step.write_google_sheet"] = Field(
        default="gui_step.write_google_sheet",
        description="Identifies a GUI Google-Sheet write step.",
    )


class RunCustomAgentStepData(BaseGuiStepSpanData[RunCustomAgentStepSpanInput]):
    type: Literal["gui_step.run_custom_agent"] = Field(
        default="gui_step.run_custom_agent",
        description=(
            "Identifies a GUI custom-agent step. A successful execution parents "
            "the workflow span for the invoked workflow."
        ),
    )


class OutputStepData(BaseGuiStepSpanData[OutputStepSpanInput]):
    type: Literal["gui_step.output"] = Field(
        default="gui_step.output",
        description="Identifies a GUI output step.",
    )


class CriticAgentStepData(BaseGuiStepSpanData[CriticAgentStepSpanInput]):
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

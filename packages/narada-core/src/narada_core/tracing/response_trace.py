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


class CriticAgentStepInput(BaseModel):
    prompt: str = Field(description="Prompt configured for the critic agent.")
    attachments: list[str] = Field(
        default_factory=list,
        description="Stable references for attachments configured on the critic.",
    )
    file_variable_attachments: list[str] = Field(
        default_factory=list,
        description="Names of file variables attached to the critic request.",
    )
    clear_chat_history: bool = Field(
        default=False,
        description="Whether the critic starts without prior agent chat history.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Names of additional tools made available to the critic.",
    )
    mcp_servers: list[str] = Field(
        default_factory=list,
        description="Stable references for MCP servers made available to the critic.",
    )
    vector_stores: list[str] = Field(
        default_factory=list,
        description="Stable references for vector stores made available to the critic.",
    )
    output_variable_names: list[str] = Field(
        default_factory=list,
        description="Workflow variable names selected for structured critic output.",
    )
    validation_variable_name: str = Field(
        description="Workflow variable containing the value validated by the critic."
    )
    on_validation_failure: dict[str, Any] = Field(
        description="Configured behavior when critic validation fails."
    )


class AgentStepInput(BaseModel):
    agent_type: AgentType = Field(description="Agent type selected in the GUI step.")
    query: str = Field(description="Effective query sent to the agent.")
    attachments: list[str] = Field(
        default_factory=list,
        description="Stable references for attachments configured on the agent.",
    )
    file_variable_attachments: list[str] = Field(
        default_factory=list,
        description="Names of file variables attached to the agent request.",
    )
    mcp_servers: list[str] = Field(
        default_factory=list,
        description="Stable references for MCP servers made available to the agent.",
    )
    vector_stores: list[str] = Field(
        default_factory=list,
        description="Stable references for vector stores made available to the agent.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Names of additional tools made available to the agent.",
    )
    output_variable_names: list[str] = Field(
        default_factory=list,
        description="Workflow variable names selected for structured agent output.",
    )
    clear_chat_history: bool = Field(
        default=False,
        description="Whether the agent starts without prior agent chat history.",
    )
    reasoning_mode: Literal["none", "low", "medium", "high"] | None = Field(
        default=None,
        description="Reasoning mode selected for the GUI agent step.",
    )
    critic: CriticAgentStepInput | None = Field(
        default=None,
        description="Critic configuration attached to the agent step, when present.",
    )


class AgenticMouseActionStepInput(BaseModel):
    page_url: str | None = Field(
        default=None,
        description="Page URL displayed from the recorded mouse action.",
    )
    page_title: str | None = Field(
        default=None,
        description="Page title displayed from the recorded mouse action.",
    )
    screenshot: str | None = Field(
        default=None,
        description="Stable reference for the recorded mouse-action preview.",
    )
    action: dict[str, Any] = Field(
        description="Configured mouse action and its action-specific values."
    )
    recorded_click: dict[str, Any] | None = Field(
        default=None,
        description="Recorded click coordinates and viewport, when available.",
    )
    resize_window: bool = Field(
        description="Whether execution resizes the browser to the recorded viewport."
    )
    fallback_operator_query: str = Field(
        description="Effective query used when the recorded action falls back to an agent."
    )
    enable_self_healing: bool = Field(
        description="Whether selector self-healing is enabled."
    )
    enable_verification: bool = Field(
        description="Whether the step verifies the mouse action after execution."
    )
    verification_description: str | None = Field(
        default=None,
        description="Condition used to verify the mouse action, when configured.",
    )
    verification_delay_ms: NonNegativeInt = Field(
        description="Delay before post-action verification, in milliseconds."
    )
    verification_status_variable_name: str | None = Field(
        default=None,
        description="Workflow variable selected to receive the verification result.",
    )


class AgenticSelectorStepInput(BaseModel):
    page_url: str | None = Field(
        default=None,
        description="Page URL displayed from the recorded element.",
    )
    page_title: str | None = Field(
        default=None,
        description="Page title displayed from the recorded element.",
    )
    screenshot: str | None = Field(
        default=None,
        description="Stable reference for the recorded element preview.",
    )
    selectors: dict[str, str] = Field(
        default_factory=dict,
        description="Effective element selectors, including CSS and XPath selectors.",
    )
    selectors_variable: str | None = Field(
        default=None,
        description="CSS-selectors workflow variable used by the step, when configured.",
    )
    selectors_variable_keys: list[str] = Field(
        default_factory=list,
        description="Selector keys read from the selectors workflow variable.",
    )
    action: dict[str, Any] = Field(
        description="Configured selector action and its action-specific values."
    )
    fallback_operator_query: str = Field(
        description="Effective query used when selector execution falls back to an agent."
    )
    enable_self_healing: bool = Field(
        description="Whether selector self-healing is enabled."
    )
    enable_intelligent_selector: bool = Field(
        default=False, description="Whether intelligent selector filtering is enabled."
    )
    nth_match: str | None = Field(
        default=None,
        description="Configured match position when multiple elements match.",
    )
    output_variable: str | None = Field(
        default=None,
        description="Workflow variable selected to receive an action result.",
    )


class RunBashScriptStepInput(BaseModel):
    code: str = Field(description="Effective Bash source executed by the step.")


class BreakStepInput(BaseModel):
    pass


class CloseTabStepInput(BaseModel):
    pass


class ContinueStepInput(BaseModel):
    pass


class DataTableExportAsCsvStepInput(BaseModel):
    data_table_input_variable: str = Field(
        description="Workflow data-table variable exported by the step."
    )


class DataTableInsertRowStepInput(BaseModel):
    data_table_input_variable: str = Field(
        description="Workflow data-table variable updated by the step."
    )
    data_record_input_variable: str = Field(
        description="Workflow object variable containing the row to insert."
    )
    insert_at: dict[str, Any] = Field(
        description="Configured first, last, or indexed insertion position."
    )


class DataTableUpdateCellValueStepInput(BaseModel):
    data_table_input_variable: str = Field(
        description="Workflow data-table variable updated by the step."
    )
    row_index: str = Field(description="Effective row index updated by the step.")
    column_locator: dict[str, str] = Field(
        description="Configured column name or column index locator."
    )
    cell_value: str = Field(description="Effective value written to the selected cell.")


class DesktopAgenticSelectorStepInput(BaseModel):
    window_title: str = Field(
        description="Effective desktop window title targeted by the step."
    )
    selectors: dict[str, Any] = Field(
        description="Recorded desktop selector values and automation technology."
    )
    action: dict[str, Any] = Field(
        description="Configured desktop action and its action-specific values."
    )


class ExecuteJavaScriptOnPageStepInput(BaseModel):
    code: str = Field(description="Effective JavaScript source executed on the page.")
    output_variable_names: list[str] = Field(
        default_factory=list,
        description="Workflow variable names populated from JavaScript results.",
    )


class OpenDesktopApplicationStepInput(BaseModel):
    executable_path: str = Field(
        description="Effective executable path opened by the step."
    )


class ReadLocalFilesystemStepInput(BaseModel):
    source_path: str = Field(
        description="Effective local filesystem path read by the step."
    )
    output_variable: str = Field(
        description="Workflow variable selected to receive the file contents."
    )


class WriteLocalFilesystemStepInput(BaseModel):
    destination_folder_path: str = Field(
        description="Effective destination folder used by the step."
    )
    input_variable: str = Field(
        description="Workflow file variable written to the local filesystem."
    )


class EndStepInput(BaseModel):
    terminate_tree: bool = Field(
        default=False,
        description="Whether the step terminates the complete workflow tree.",
    )
    result_status: Literal["success", "error"] | None = Field(
        default=None,
        description="Workflow result selected when the complete tree is terminated.",
    )
    message: str | None = Field(
        default=None,
        description="Effective workflow result message configured on the step.",
    )


class OutputVariableStepInput(BaseModel):
    output_variable: str = Field(
        description="Workflow variable selected to receive the step result."
    )


class SavePdfFileStepInput(OutputVariableStepInput):
    pass


class GetFullHtmlStepInput(OutputVariableStepInput):
    pass


class GetScreenshotStepInput(OutputVariableStepInput):
    pass


class GetSimplifiedHtmlStepInput(OutputVariableStepInput):
    pass


class GetUrlStepInput(OutputVariableStepInput):
    pass


class GoToUrlStepInput(BaseModel):
    url: str = Field(description="Effective destination URL used by the step.")


class HttpRequestAuthInput(BaseModel):
    type: Literal["none", "bearer", "api_key"] = Field(
        description="Authentication mode selected for the request."
    )
    token: str | None = Field(
        default=None,
        description="Redacted authentication token, when the mode uses one.",
    )
    header_name: str | None = Field(
        default=None,
        description="API-key header name, when configured.",
    )


class HttpRequestMultipartInput(BaseModel):
    fields: list[dict[str, str]] = Field(
        default_factory=list,
        description="Effective multipart text fields sent by the request.",
    )
    file: dict[str, Any] | None = Field(
        default=None,
        description="Stable reference for the multipart file, when configured.",
    )


class HttpRequestStepInput(BaseModel):
    url: str = Field(description="Effective URL requested by the step.")
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = Field(
        description="HTTP method used by the request."
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Effective request headers with secret values redacted.",
    )
    auth: HttpRequestAuthInput = Field(
        description="Redacted authentication configuration used by the request."
    )
    body_mode: Literal["none", "raw", "multipart"] = Field(
        description="Request body mode selected for the step."
    )
    body_template: str | None = Field(
        default=None,
        description="Effective raw request body, when configured.",
    )
    multipart: HttpRequestMultipartInput | None = Field(
        default=None,
        description="Effective multipart body, when configured.",
    )
    timeout_ms: NonNegativeInt = Field(
        description="Configured request timeout in milliseconds."
    )
    output_variable: str = Field(
        description="Workflow variable selected to receive the response body."
    )


class ConditionalBranchInput(BaseModel):
    name: str | None = Field(
        default=None,
        description="Optional user-facing name of the branch.",
    )
    condition: dict[str, Any] = Field(
        description="Authored condition controlling the branch."
    )


class IfStepInput(BaseModel):
    condition: dict[str, Any] = Field(
        description="Authored condition controlling the then branch."
    )
    then_branch_name: str | None = Field(
        default=None,
        description="Optional user-facing name of the then branch.",
    )
    else_if_branches: list[ConditionalBranchInput] = Field(
        default_factory=list,
        description="Authored else-if branch names and conditions.",
    )
    else_branch_name: str | None = Field(
        default=None,
        description="Optional user-facing name of the else branch.",
    )


class LogVariablesToFileStepInput(BaseModel):
    file_name: str = Field(description="Effective name of the generated log file.")
    variables_to_log: list[str] = Field(
        description="Workflow variables selected for the log file."
    )


class ObjectExportAsJsonStepInput(BaseModel):
    object_input_variable: str = Field(
        description="Workflow object variable exported as JSON."
    )


class ObjectPropertyAssignmentInput(BaseModel):
    name: str = Field(description="Object property name updated by the step.")
    value: str = Field(description="Effective value assigned to the object property.")


class ObjectSetPropertiesStepInput(BaseModel):
    object_output_variable: str = Field(
        description="Workflow object variable updated by the step."
    )
    properties: list[ObjectPropertyAssignmentInput] = Field(
        description="Effective object property assignments."
    )


class PressKeysStepInput(BaseModel):
    recorded_keys: list[dict[str, Any]] = Field(
        description="Recorded key events replayed by the step."
    )


class PrintStepInput(BaseModel):
    message: str = Field(description="Effective message emitted by the step.")


class NaradaCodeProjectExecutableStepInput(BaseModel):
    narada_code_project_id: str = Field(
        description="Stable identifier of the Narada Code project."
    )
    executable_project_relative_path: str = Field(
        description="Project-relative path of the executable."
    )
    argument_string: str = Field(
        description="Effective argument string passed to the executable."
    )


class PythonStepInput(BaseModel):
    code: str = Field(description="Effective Python source executed by the step.")


class ReadCsvStepInput(BaseModel):
    content: str = Field(description="Effective CSV content parsed by the step.")
    output_variable: str = Field(
        description="Workflow variable selected to receive the parsed data table."
    )


class ReadExcelSheetStepInput(BaseModel):
    workbook_url: str = Field(description="Effective Excel workbook URL.")
    range: str = Field(description="Effective Excel range read by the step.")
    microsoft_account_email: str = Field(
        description="Microsoft account selected for the workbook."
    )
    has_headers: bool = Field(
        description="Whether the first spreadsheet row is interpreted as headers."
    )
    output_variable: str = Field(
        description="Workflow variable selected to receive the sheet data."
    )


class ReadGoogleSheetStepInput(BaseModel):
    spreadsheet_url: str = Field(description="Effective Google spreadsheet URL.")
    range: str = Field(description="Effective Google Sheets range read by the step.")
    has_headers: bool = Field(
        description="Whether the first spreadsheet row is interpreted as headers."
    )
    output_variable: str = Field(
        description="Workflow variable selected to receive the sheet data."
    )


class SlackActionStepInput(BaseModel):
    connector: str = Field(description="Stable reference for the selected connector.")
    target: str = Field(description="Effective Slack target.")
    message: str = Field(description="Effective Slack message.")
    output_variable: str | None = Field(
        default=None,
        description="Workflow variable selected to receive the Slack result.",
    )


class SetVariableStepInput(BaseModel):
    output_variable: str = Field(description="Workflow variable updated by the step.")
    new_value: Any = Field(description="Effective value assigned to the variable.")


class PromptForUserInputVariable(BaseModel):
    name: str = Field(description="Workflow variable populated by the user.")
    required: bool = Field(description="Whether the user must provide the variable.")


class PromptForUserInputStepInput(BaseModel):
    prompt_message: str | None = Field(
        default=None,
        description="Effective prompt presented to the user.",
    )
    variables_to_prompt: list[PromptForUserInputVariable] = Field(
        description="Workflow variables requested from the user."
    )


class StartStepInput(BaseModel):
    pass


class ThrowStepInput(BaseModel):
    message: str = Field(description="Effective error message thrown by the step.")


class CatchBranchInput(BaseModel):
    name: str | None = Field(
        default=None,
        description="Optional user-facing name of the catch branch.",
    )
    condition: dict[str, Any] | None = Field(
        default=None,
        description="Authored condition controlling the catch branch.",
    )


class TryCatchStepInput(BaseModel):
    try_branch_name: str | None = Field(
        default=None,
        description="Optional user-facing name of the try branch.",
    )
    catch_branches: list[CatchBranchInput] = Field(
        description="Authored catch branch names and conditions."
    )
    finally_branch_name: str | None = Field(
        default=None,
        description="Optional user-facing name of the finally branch.",
    )


class UserApprovalStepInput(BaseModel):
    prompt_message: str = Field(description="Effective approval prompt.")
    approve_label: str = Field(description="Label displayed for approval.")
    reject_label: str = Field(description="Label displayed for rejection.")
    output_variable: str = Field(
        description="Workflow variable selected to receive the approval result."
    )


class WaitStepInput(BaseModel):
    duration: str | float = Field(description="Effective wait duration.")


class WaitForElementStepInput(BaseModel):
    page_url: str | None = Field(
        default=None,
        description="Page URL displayed from the recorded element.",
    )
    page_title: str | None = Field(
        default=None,
        description="Page title displayed from the recorded element.",
    )
    selectors: dict[str, str] = Field(
        description="Effective selectors used to locate the element."
    )
    state: Literal["exists", "doesNotExist"] = Field(
        description="Element state awaited by the step."
    )
    timeout: NonNegativeInt = Field(
        description="Configured element wait timeout in milliseconds."
    )
    output_variable: str = Field(
        description="Workflow variable selected to receive the observed boolean."
    )


class WhileStepInput(BaseModel):
    condition: dict[str, Any] = Field(
        description="Authored condition evaluated before each iteration."
    )
    max_iterations: str | None = Field(
        default=None,
        description="Effective maximum iteration count, when configured.",
    )
    index_output_variable: str | None = Field(
        default=None,
        description="Workflow variable selected to receive the loop index.",
    )


class WriteExcelSheetStepInput(BaseModel):
    workbook_url: str = Field(description="Effective Excel workbook URL.")
    range: str = Field(description="Effective Excel range written by the step.")
    microsoft_account_email: str = Field(
        description="Microsoft account selected for the workbook."
    )
    data_table_input_variable: str = Field(
        description="Workflow data-table variable written to the workbook."
    )
    include_headers: bool = Field(
        description="Whether data-table headers are included in the write."
    )


class WriteGoogleSheetStepInput(BaseModel):
    spreadsheet_url: str = Field(description="Effective Google spreadsheet URL.")
    range: str = Field(description="Effective Google Sheets range written by the step.")
    data_table_input_variable: str = Field(
        description="Workflow data-table variable written to the spreadsheet."
    )
    include_headers: bool = Field(
        description="Whether data-table headers are included in the write."
    )


class VariableMappingInput(BaseModel):
    parent_variable: str = Field(description="Variable name in the parent workflow.")
    child_variable: str = Field(description="Variable name in the child workflow.")


class OutputVariableMappingInput(BaseModel):
    child_variable: str = Field(description="Output variable in the child workflow.")
    parent_variable: str = Field(
        description="Workflow variable updated in the parent workflow."
    )


class RunCustomAgentStepInput(BaseModel):
    workflow_id: str = Field(
        description="Stable identifier of the invoked custom workflow."
    )
    workflow_name: str | None = Field(
        default=None,
        description="Display name of the invoked custom workflow.",
    )
    prompt: str = Field(description="Effective prompt sent to the custom workflow.")
    input_variables_mapping: list[VariableMappingInput] = Field(
        description="Parent-to-child workflow input mappings."
    )
    output_variables_mapping: list[OutputVariableMappingInput] = Field(
        description="Child-to-parent workflow output mappings."
    )


class OutputStepInput(BaseModel):
    variables_to_output: list[str] = Field(
        description="Workflow variables selected as workflow outputs."
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
    output_variables: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Workflow variable names and runtime values written by this step execution."
        ),
    )


class AgentStepData(AgentStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.agent"] = Field(
        default="gui_step.agent",
        description="Identifies a GUI agent step.",
    )


class AgenticMouseActionStepData(AgenticMouseActionStepInput, BaseGuiStepSpanData):
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


class AgenticSelectorStepData(AgenticSelectorStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.agentic_selector"] = Field(
        default="gui_step.agentic_selector",
        description="Identifies a GUI agentic selector step.",
    )
    strategy: Literal["selector", "operator_fallback"] = Field(
        description="Execution path that ultimately selected the element."
    )


class RunBashScriptStepData(RunBashScriptStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.run_bash_script"] = Field(
        default="gui_step.run_bash_script",
        description="Identifies a GUI run-Bash-script step.",
    )


class BreakStepData(BreakStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.break"] = Field(
        default="gui_step.break",
        description="Identifies a GUI break step.",
    )


class CloseTabStepData(CloseTabStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.close_tab"] = Field(
        default="gui_step.close_tab",
        description="Identifies a GUI close-tab step.",
    )


class ContinueStepData(ContinueStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.continue"] = Field(
        default="gui_step.continue",
        description="Identifies a GUI continue step.",
    )


class DataTableExportAsCsvStepData(DataTableExportAsCsvStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.data_table_export_as_csv"] = Field(
        default="gui_step.data_table_export_as_csv",
        description="Identifies a GUI data-table CSV export step.",
    )


class DataTableInsertRowStepData(DataTableInsertRowStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.data_table_insert_row"] = Field(
        default="gui_step.data_table_insert_row",
        description="Identifies a GUI data-table row insertion step.",
    )


class DataTableUpdateCellValueStepData(
    DataTableUpdateCellValueStepInput, BaseGuiStepSpanData
):
    type: Literal["gui_step.data_table_update_cell_value"] = Field(
        default="gui_step.data_table_update_cell_value",
        description="Identifies a GUI data-table cell update step.",
    )


class DesktopAgenticSelectorStepData(
    DesktopAgenticSelectorStepInput, BaseGuiStepSpanData
):
    type: Literal["gui_step.desktop_agentic_selector"] = Field(
        default="gui_step.desktop_agentic_selector",
        description="Identifies a GUI desktop agentic selector step.",
    )


class ExecuteJavaScriptOnPageStepData(
    ExecuteJavaScriptOnPageStepInput, BaseGuiStepSpanData
):
    type: Literal["gui_step.execute_javascript_on_page"] = Field(
        default="gui_step.execute_javascript_on_page",
        description="Identifies a GUI in-page JavaScript execution step.",
    )


class OpenDesktopApplicationStepData(
    OpenDesktopApplicationStepInput, BaseGuiStepSpanData
):
    type: Literal["gui_step.open_desktop_application"] = Field(
        default="gui_step.open_desktop_application",
        description="Identifies a GUI open-desktop-application step.",
    )


class ReadLocalFilesystemStepData(ReadLocalFilesystemStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.read_local_filesystem"] = Field(
        default="gui_step.read_local_filesystem",
        description="Identifies a GUI local-filesystem read step.",
    )


class WriteLocalFilesystemStepData(WriteLocalFilesystemStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.write_local_filesystem"] = Field(
        default="gui_step.write_local_filesystem",
        description="Identifies a GUI local-filesystem write step.",
    )


class EndStepData(EndStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.end"] = Field(
        default="gui_step.end",
        description="Identifies a GUI end step.",
    )


class ForStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.for"] = Field(
        default="gui_step.for",
        description="Identifies a GUI for-loop step.",
    )
    loop_type: Literal["nTimes", "forEachRowInDataTable", "forEachItemsInArray"] = (
        Field(description="Configured loop mode.")
    )
    index_output_variable: str | None = Field(
        default=None,
        description="Workflow variable selected to receive the loop index.",
    )
    iterations: str | None = Field(
        default=None,
        description="Effective number of requested iterations for a fixed-count loop.",
    )
    data_table_input_variable: str | None = Field(
        default=None,
        description="Workflow data-table variable iterated by a row loop.",
    )
    row_output_variable: str | None = Field(
        default=None,
        description="Workflow variable receiving the current row.",
    )
    array_input_variable: str | None = Field(
        default=None,
        description="Workflow array variable iterated by an item loop.",
    )
    item_output_variable: str | None = Field(
        default=None,
        description="Workflow variable receiving the current item.",
    )
    total_iterations: NonNegativeInt = Field(
        description="Number of loop iterations that started during this execution."
    )


class SavePdfFileStepData(SavePdfFileStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.save_pdf_file"] = Field(
        default="gui_step.save_pdf_file",
        description="Identifies a GUI save-PDF-file step.",
    )


class GetFullHtmlStepData(GetFullHtmlStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.get_full_html"] = Field(
        default="gui_step.get_full_html",
        description="Identifies a GUI full-HTML retrieval step.",
    )


class GetScreenshotStepData(GetScreenshotStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.get_screenshot"] = Field(
        default="gui_step.get_screenshot",
        description="Identifies a GUI screenshot step.",
    )


class GetSimplifiedHtmlStepData(GetSimplifiedHtmlStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.get_simplified_html"] = Field(
        default="gui_step.get_simplified_html",
        description="Identifies a GUI simplified-HTML retrieval step.",
    )


class GetUrlStepData(GetUrlStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.get_url"] = Field(
        default="gui_step.get_url",
        description="Identifies a GUI get-URL step.",
    )


class GoToUrlStepData(GoToUrlStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.go_to_url"] = Field(
        default="gui_step.go_to_url",
        description="Identifies a GUI go-to-URL step.",
    )


class HttpRequestStepData(HttpRequestStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.http_request"] = Field(
        default="gui_step.http_request",
        description="Identifies a GUI HTTP-request step.",
    )


class IfStepData(IfStepInput, BaseGuiStepSpanData):
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


class LogVariablesToFileStepData(LogVariablesToFileStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.log_variables_to_file"] = Field(
        default="gui_step.log_variables_to_file",
        description="Identifies a GUI variable-log file step.",
    )


class ObjectExportAsJsonStepData(ObjectExportAsJsonStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.object_export_as_json"] = Field(
        default="gui_step.object_export_as_json",
        description="Identifies a GUI object JSON export step.",
    )


class ObjectSetPropertiesStepData(ObjectSetPropertiesStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.object_set_properties"] = Field(
        default="gui_step.object_set_properties",
        description="Identifies a GUI object-property update step.",
    )


class PressKeysStepData(PressKeysStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.press_keys"] = Field(
        default="gui_step.press_keys",
        description="Identifies a GUI key-press step.",
    )


class PrintStepData(PrintStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.print"] = Field(
        default="gui_step.print",
        description="Identifies a GUI print step.",
    )


class NaradaCodeProjectExecutableStepData(
    NaradaCodeProjectExecutableStepInput, BaseGuiStepSpanData
):
    type: Literal["gui_step.narada_code_project_executable"] = Field(
        default="gui_step.narada_code_project_executable",
        description="Identifies a GUI Narada Code project-executable step.",
    )


class PythonStepData(PythonStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.python"] = Field(
        default="gui_step.python",
        description="Identifies a GUI Python execution step.",
    )


class ReadCsvStepData(ReadCsvStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.read_csv"] = Field(
        default="gui_step.read_csv",
        description="Identifies a GUI CSV-read step.",
    )


class ReadExcelSheetStepData(ReadExcelSheetStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.read_excel_sheet"] = Field(
        default="gui_step.read_excel_sheet",
        description="Identifies a GUI Excel-sheet read step.",
    )


class ReadGoogleSheetStepData(ReadGoogleSheetStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.read_google_sheet"] = Field(
        default="gui_step.read_google_sheet",
        description="Identifies a GUI Google-Sheet read step.",
    )


class EmailActionStepData(BaseGuiStepSpanData):
    type: Literal["gui_step.email_action"] = Field(
        default="gui_step.email_action",
        description="Identifies a GUI email action step.",
    )
    action: Literal["send", "getMany", "markRead", "markUnread", "getById"] = Field(
        description="Email operation performed by the step."
    )
    connector: str = Field(description="Stable reference for the selected connector.")
    output_variable: str | None = Field(
        default=None,
        description="Workflow variable selected to receive the provider result.",
    )
    to: str | None = Field(
        default=None,
        description="Effective primary recipients for a send operation.",
    )
    cc: str | None = Field(
        default=None,
        description="Effective carbon-copy recipients for a send operation.",
    )
    bcc: str | None = Field(
        default=None,
        description="Effective blind-carbon-copy recipients for a send operation.",
    )
    subject: str | None = Field(
        default=None,
        description="Effective email subject for a send operation.",
    )
    body: str | None = Field(
        default=None,
        description="Effective email body for a send operation.",
    )
    file_variable_attachments: list[str] = Field(
        default_factory=list,
        description="Names of file variables attached to a sent email.",
    )
    gmail_filters: dict[str, Any] | None = Field(
        default=None,
        description="Filters applied by a multi-email retrieval operation.",
    )
    max_results: NonNegativeInt | None = Field(
        default=None,
        description="Maximum number of emails requested by a retrieval operation.",
    )
    message_id: str | None = Field(
        default=None,
        description="Effective message identifier used by a message operation.",
    )
    attachment_output_variable: str | None = Field(
        default=None,
        description="Workflow variable selected to receive downloaded attachments.",
    )
    download_attachments: bool | None = Field(
        default=None,
        description="Whether a single-email retrieval downloaded attachments.",
    )


class SlackActionStepData(SlackActionStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.slack_action"] = Field(
        default="gui_step.slack_action",
        description="Identifies a GUI Slack action step.",
    )


class SetVariableStepData(SetVariableStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.set_variable"] = Field(
        default="gui_step.set_variable",
        description="Identifies a GUI set-variable step.",
    )


class PromptForUserInputStepData(PromptForUserInputStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.prompt_for_user_input"] = Field(
        default="gui_step.prompt_for_user_input",
        description="Identifies a GUI user-input prompt step.",
    )


class StartStepData(StartStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.start"] = Field(
        default="gui_step.start",
        description="Identifies a GUI start step.",
    )


class ThrowStepData(ThrowStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.throw"] = Field(
        default="gui_step.throw",
        description="Identifies a GUI throw step.",
    )


class TryCatchStepData(TryCatchStepInput, BaseGuiStepSpanData):
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


class UserApprovalStepData(UserApprovalStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.user_approval"] = Field(
        default="gui_step.user_approval",
        description="Identifies a GUI user-approval step.",
    )


class WaitStepData(WaitStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.wait"] = Field(
        default="gui_step.wait",
        description="Identifies a GUI wait step.",
    )


class WaitForElementStepData(WaitForElementStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.wait_for_element"] = Field(
        default="gui_step.wait_for_element",
        description="Identifies a GUI wait-for-element step.",
    )


class WhileStepData(WhileStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.while"] = Field(
        default="gui_step.while",
        description="Identifies a GUI while-loop step.",
    )
    total_iterations: NonNegativeInt = Field(
        description="Number of loop iterations that started during this execution."
    )


class WriteExcelSheetStepData(WriteExcelSheetStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.write_excel_sheet"] = Field(
        default="gui_step.write_excel_sheet",
        description="Identifies a GUI Excel-sheet write step.",
    )


class WriteGoogleSheetStepData(WriteGoogleSheetStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.write_google_sheet"] = Field(
        default="gui_step.write_google_sheet",
        description="Identifies a GUI Google-Sheet write step.",
    )


class RunCustomAgentStepData(RunCustomAgentStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.run_custom_agent"] = Field(
        default="gui_step.run_custom_agent",
        description=(
            "Identifies a GUI custom-agent step. A successful execution parents "
            "the workflow span for the invoked workflow."
        ),
    )


class OutputStepData(OutputStepInput, BaseGuiStepSpanData):
    type: Literal["gui_step.output"] = Field(
        default="gui_step.output",
        description="Identifies a GUI output step.",
    )


class CriticAgentStepData(CriticAgentStepInput, BaseGuiStepSpanData):
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


TSpanData = TypeVar("TSpanData", bound=SpanDataUnion)


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
    "CatchBranchInput",
    "CatchSpanData",
    "CloseTabStepData",
    "ConditionalBranchInput",
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
    "HttpRequestAuthInput",
    "HttpRequestMultipartInput",
    "HttpRequestStepData",
    "IfStepData",
    "IterationSpanData",
    "LogVariablesToFileStepData",
    "NaradaCodeProjectExecutableStepData",
    "ObjectExportAsJsonStepData",
    "ObjectPropertyAssignmentInput",
    "ObjectSetPropertiesStepData",
    "OpenDesktopApplicationStepData",
    "OutputStepData",
    "OutputVariableMappingInput",
    "PressKeysStepData",
    "PrintStepData",
    "PromptForUserInputVariable",
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
    "VariableMappingInput",
    "WaitForElementStepData",
    "WaitStepData",
    "WhileStepData",
    "WorkflowSpanData",
    "WorkflowSpanStatus",
    "WriteExcelSheetStepData",
    "WriteGoogleSheetStepData",
    "WriteLocalFilesystemStepData",
]

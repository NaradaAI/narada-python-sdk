"""Trace-safe input snapshots for GUI step spans."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, NonNegativeInt

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


class CriticAgentStepSpanInput(BaseModel):
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


class AgentStepSpanInput(BaseModel):
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
    critic: CriticAgentStepSpanInput | None = Field(
        default=None,
        description="Critic configuration attached to the agent step, when present.",
    )


class AgenticMouseActionStepSpanInput(BaseModel):
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


class AgenticSelectorStepSpanInput(BaseModel):
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


class RunBashScriptStepSpanInput(BaseModel):
    code: str = Field(description="Effective Bash source executed by the step.")


class BreakStepSpanInput(BaseModel):
    pass


class CloseTabStepSpanInput(BaseModel):
    pass


class ContinueStepSpanInput(BaseModel):
    pass


class DataTableExportAsCsvStepSpanInput(BaseModel):
    data_table_input_variable: str = Field(
        description="Workflow data-table variable exported by the step."
    )


class DataTableInsertRowStepSpanInput(BaseModel):
    data_table_input_variable: str = Field(
        description="Workflow data-table variable updated by the step."
    )
    data_record_input_variable: str = Field(
        description="Workflow object variable containing the row to insert."
    )
    insert_at: dict[str, Any] = Field(
        description="Configured first, last, or indexed insertion position."
    )


class DataTableUpdateCellValueStepSpanInput(BaseModel):
    data_table_input_variable: str = Field(
        description="Workflow data-table variable updated by the step."
    )
    row_index: str = Field(description="Effective row index updated by the step.")
    column_locator: dict[str, str] = Field(
        description="Configured column name or column index locator."
    )
    cell_value: str = Field(description="Effective value written to the selected cell.")


class DesktopAgenticSelectorStepSpanInput(BaseModel):
    window_title: str = Field(
        description="Effective desktop window title targeted by the step."
    )
    selectors: dict[str, Any] = Field(
        description="Recorded desktop selector values and automation technology."
    )
    action: dict[str, Any] = Field(
        description="Configured desktop action and its action-specific values."
    )


class ExecuteJavaScriptOnPageStepSpanInput(BaseModel):
    code: str = Field(description="Effective JavaScript source executed on the page.")
    output_variable_names: list[str] = Field(
        default_factory=list,
        description="Workflow variable names populated from JavaScript results.",
    )


class OpenDesktopApplicationStepSpanInput(BaseModel):
    executable_path: str = Field(
        description="Effective executable path opened by the step."
    )


class ReadLocalFilesystemStepSpanInput(BaseModel):
    source_path: str = Field(
        description="Effective local filesystem path read by the step."
    )
    output_variable: str = Field(
        description="Workflow variable selected to receive the file contents."
    )


class WriteLocalFilesystemStepSpanInput(BaseModel):
    destination_folder_path: str = Field(
        description="Effective destination folder used by the step."
    )
    input_variable: str = Field(
        description="Workflow file variable written to the local filesystem."
    )


class EndStepSpanInput(BaseModel):
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


class ForStepSpanInput(BaseModel):
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


class OutputVariableStepSpanInput(BaseModel):
    output_variable: str = Field(
        description="Workflow variable selected to receive the step result."
    )


class SavePdfFileStepSpanInput(OutputVariableStepSpanInput):
    pass


class GetFullHtmlStepSpanInput(OutputVariableStepSpanInput):
    pass


class GetScreenshotStepSpanInput(OutputVariableStepSpanInput):
    pass


class GetSimplifiedHtmlStepSpanInput(OutputVariableStepSpanInput):
    pass


class GetUrlStepSpanInput(OutputVariableStepSpanInput):
    pass


class GoToUrlStepSpanInput(BaseModel):
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


class HttpRequestStepSpanInput(BaseModel):
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


class IfStepSpanInput(BaseModel):
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


class LogVariablesToFileStepSpanInput(BaseModel):
    file_name: str = Field(description="Effective name of the generated log file.")
    variables_to_log: list[str] = Field(
        description="Workflow variables selected for the log file."
    )


class ObjectExportAsJsonStepSpanInput(BaseModel):
    object_input_variable: str = Field(
        description="Workflow object variable exported as JSON."
    )


class ObjectPropertyAssignmentInput(BaseModel):
    name: str = Field(description="Object property name updated by the step.")
    value: str = Field(description="Effective value assigned to the object property.")


class ObjectSetPropertiesStepSpanInput(BaseModel):
    object_output_variable: str = Field(
        description="Workflow object variable updated by the step."
    )
    properties: list[ObjectPropertyAssignmentInput] = Field(
        description="Effective object property assignments."
    )


class PressKeysStepSpanInput(BaseModel):
    recorded_keys: list[dict[str, Any]] = Field(
        description="Recorded key events replayed by the step."
    )


class PrintStepSpanInput(BaseModel):
    message: str = Field(description="Effective message emitted by the step.")


class NaradaCodeProjectExecutableStepSpanInput(BaseModel):
    narada_code_project_id: str = Field(
        description="Stable identifier of the Narada Code project."
    )
    executable_project_relative_path: str = Field(
        description="Project-relative path of the executable."
    )
    argument_string: str = Field(
        description="Effective argument string passed to the executable."
    )


class PythonStepSpanInput(BaseModel):
    code: str = Field(description="Effective Python source executed by the step.")


class ReadCsvStepSpanInput(BaseModel):
    content: str = Field(description="Effective CSV content parsed by the step.")
    output_variable: str = Field(
        description="Workflow variable selected to receive the parsed data table."
    )


class ReadExcelSheetStepSpanInput(BaseModel):
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


class ReadGoogleSheetStepSpanInput(BaseModel):
    spreadsheet_url: str = Field(description="Effective Google spreadsheet URL.")
    range: str = Field(description="Effective Google Sheets range read by the step.")
    has_headers: bool = Field(
        description="Whether the first spreadsheet row is interpreted as headers."
    )
    output_variable: str = Field(
        description="Workflow variable selected to receive the sheet data."
    )


class EmailActionStepSpanInput(BaseModel):
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


class SlackActionStepSpanInput(BaseModel):
    connector: str = Field(description="Stable reference for the selected connector.")
    target: str = Field(description="Effective Slack target.")
    message: str = Field(description="Effective Slack message.")
    output_variable: str | None = Field(
        default=None,
        description="Workflow variable selected to receive the Slack result.",
    )


class SetVariableStepSpanInput(BaseModel):
    output_variable: str = Field(description="Workflow variable updated by the step.")
    new_value: Any = Field(description="Effective value assigned to the variable.")


class PromptForUserInputVariable(BaseModel):
    name: str = Field(description="Workflow variable populated by the user.")
    required: bool = Field(description="Whether the user must provide the variable.")


class PromptForUserInputStepSpanInput(BaseModel):
    prompt_message: str | None = Field(
        default=None,
        description="Effective prompt presented to the user.",
    )
    variables_to_prompt: list[PromptForUserInputVariable] = Field(
        description="Workflow variables requested from the user."
    )


class StartStepSpanInput(BaseModel):
    pass


class ThrowStepSpanInput(BaseModel):
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


class TryCatchStepSpanInput(BaseModel):
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


class UserApprovalStepSpanInput(BaseModel):
    prompt_message: str = Field(description="Effective approval prompt.")
    approve_label: str = Field(description="Label displayed for approval.")
    reject_label: str = Field(description="Label displayed for rejection.")
    output_variable: str = Field(
        description="Workflow variable selected to receive the approval result."
    )


class WaitStepSpanInput(BaseModel):
    duration: str | float = Field(description="Effective wait duration.")


class WaitForElementStepSpanInput(BaseModel):
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


class WhileStepSpanInput(BaseModel):
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


class WriteExcelSheetStepSpanInput(BaseModel):
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


class WriteGoogleSheetStepSpanInput(BaseModel):
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


class RunCustomAgentStepSpanInput(BaseModel):
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


class OutputStepSpanInput(BaseModel):
    variables_to_output: list[str] = Field(
        description="Workflow variables selected as workflow outputs."
    )


type GuiStepSpanInput = (
    AgentStepSpanInput
    | AgenticMouseActionStepSpanInput
    | AgenticSelectorStepSpanInput
    | BreakStepSpanInput
    | CloseTabStepSpanInput
    | ContinueStepSpanInput
    | CriticAgentStepSpanInput
    | DataTableExportAsCsvStepSpanInput
    | DataTableInsertRowStepSpanInput
    | DataTableUpdateCellValueStepSpanInput
    | DesktopAgenticSelectorStepSpanInput
    | EmailActionStepSpanInput
    | EndStepSpanInput
    | ExecuteJavaScriptOnPageStepSpanInput
    | ForStepSpanInput
    | GetFullHtmlStepSpanInput
    | GetScreenshotStepSpanInput
    | GetSimplifiedHtmlStepSpanInput
    | GetUrlStepSpanInput
    | GoToUrlStepSpanInput
    | HttpRequestStepSpanInput
    | IfStepSpanInput
    | LogVariablesToFileStepSpanInput
    | NaradaCodeProjectExecutableStepSpanInput
    | ObjectExportAsJsonStepSpanInput
    | ObjectSetPropertiesStepSpanInput
    | OpenDesktopApplicationStepSpanInput
    | OutputStepSpanInput
    | PressKeysStepSpanInput
    | PrintStepSpanInput
    | PromptForUserInputStepSpanInput
    | PythonStepSpanInput
    | ReadCsvStepSpanInput
    | ReadExcelSheetStepSpanInput
    | ReadGoogleSheetStepSpanInput
    | ReadLocalFilesystemStepSpanInput
    | RunBashScriptStepSpanInput
    | RunCustomAgentStepSpanInput
    | SavePdfFileStepSpanInput
    | SetVariableStepSpanInput
    | SlackActionStepSpanInput
    | StartStepSpanInput
    | ThrowStepSpanInput
    | TryCatchStepSpanInput
    | UserApprovalStepSpanInput
    | WaitForElementStepSpanInput
    | WaitStepSpanInput
    | WhileStepSpanInput
    | WriteExcelSheetStepSpanInput
    | WriteGoogleSheetStepSpanInput
    | WriteLocalFilesystemStepSpanInput
)

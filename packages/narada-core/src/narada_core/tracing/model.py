from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    Field,
    NonNegativeInt,
    TypeAdapter,
    ValidationError,
    model_validator,
)


class OperatorActionTraceItem(BaseModel):
    url: str
    action: str


class GoToUrlTrace(BaseModel):
    step_type: Literal["goToUrl"]
    url: str
    description: str


class GetUrlTrace(BaseModel):
    step_type: Literal["getUrl"]
    url: str
    description: str


class PrintTrace(BaseModel):
    step_type: Literal["print"]
    url: str
    message: str


class AgentTrace(BaseModel):
    step_type: Literal["agent"]
    url: str
    agent_type: str
    action_trace: ActionTrace | None = None
    text: str | None = None


class ForLoopTrace(BaseModel):
    step_type: Literal["for"]
    url: str
    loop_type: Literal["nTimes", "forEachRowInDataTable", "forEachItemsInArray"]
    description: str
    iterations: list[ApaActionTrace]  # Recursive reference


class WhileLoopTrace(BaseModel):
    step_type: Literal["while"]
    url: str
    condition: str
    iterations: list[ApaActionTrace]  # Recursive reference
    total_iterations: int


class AgenticSelectorTrace(BaseModel):
    step_type: Literal["agenticSelector"]
    url: str
    description: str
    action_trace: ActionTrace | None = None


class AgenticMouseActionTrace(BaseModel):
    step_type: Literal["agenticMouseAction"]
    url: str
    description: str
    action_trace: ActionTrace | None = None


class WaitForElementTrace(BaseModel):
    step_type: Literal["waitForElement"]
    url: str
    description: str


class PressKeysTrace(BaseModel):
    step_type: Literal["pressKeys"]
    url: str
    description: str


class ReadGoogleSheetTrace(BaseModel):
    step_type: Literal["readGoogleSheet"]
    url: str
    description: str


class WriteGoogleSheetTrace(BaseModel):
    step_type: Literal["writeGoogleSheet"]
    url: str
    description: str


class DataTableExportAsCsvTrace(BaseModel):
    step_type: Literal["dataTableExportAsCsv"]
    url: str
    description: str


class PythonTrace(BaseModel):
    step_type: Literal["python"]
    url: str
    description: str


class ReadCsvTrace(BaseModel):
    step_type: Literal["readCsv"]
    url: str
    description: str


class StartTrace(BaseModel):
    step_type: Literal["start"]
    url: str
    description: str


class EndTrace(BaseModel):
    step_type: Literal["end"]
    url: str
    description: str


class GetFullHtmlTrace(BaseModel):
    step_type: Literal["getFullHtml"]
    url: str
    description: str


class GetSimplifiedHtmlTrace(BaseModel):
    step_type: Literal["getSimplifiedHtml"]
    url: str
    description: str


class GetScreenshotTrace(BaseModel):
    step_type: Literal["getScreenshot"]
    url: str
    description: str


class ObjectExportAsJsonTrace(BaseModel):
    step_type: Literal["objectExportAsJson"]
    url: str
    description: str


class RunCustomAgentTrace(BaseModel):
    step_type: Literal["runCustomAgent"]
    url: str
    workflow_id: str
    workflow_name: str
    status: Literal["success", "error"]
    error_message: str | None = None


class IfTrace(BaseModel):
    step_type: Literal["if"]
    url: str
    description: str


class SetVariableTrace(BaseModel):
    step_type: Literal["setVariable"]
    url: str
    description: str


class WaitTrace(BaseModel):
    step_type: Literal["wait"]
    url: str
    description: str


class DataTableInsertRowTrace(BaseModel):
    step_type: Literal["dataTableInsertRow"]
    url: str
    description: str


class DataTableUpdateCellValueTrace(BaseModel):
    step_type: Literal["dataTableUpdateCellValue"]
    url: str
    description: str


class ObjectSetPropertiesTrace(BaseModel):
    step_type: Literal["objectSetProperties"]
    url: str
    description: str


class OutputTrace(BaseModel):
    step_type: Literal["output"]
    description: str


# ---------------------------------------------------------------------------
# Python agent run trace: emitted by CustomPythonAgentRunnable for custom
# Python agents executed in the browser Pyodide runtime. A single
# PythonAgentRunTrace wraps the full agent's execution; its `events` list is
# a chronologically sorted timeline of stdout / stderr / SDK call events.
# ---------------------------------------------------------------------------


class PythonStdoutEvent(BaseModel):
    kind: Literal["stdout"] = "stdout"
    ts: int
    text: str


class PythonStderrEvent(BaseModel):
    kind: Literal["stderr"] = "stderr"
    ts: int
    text: str


class PythonSubAgentCallEvent(BaseModel):
    kind: Literal["subAgentCall"] = "subAgentCall"
    ts_start: int
    ts_end: int
    agent_type: str
    prompt: str
    status: Literal["success", "error", "timeout"]
    request_id: str | None = None
    error_message: str | None = None
    action_trace: ActionTrace | None = None

    @model_validator(mode="after")
    def _check_ts_ordering(self) -> PythonSubAgentCallEvent:
        if self.ts_end < self.ts_start:
            raise ValueError(
                f"PythonSubAgentCallEvent: ts_end ({self.ts_end}) must be >= ts_start ({self.ts_start})"
            )
        return self


class PythonExtensionActionEvent(BaseModel):
    kind: Literal["extensionAction"] = "extensionAction"
    ts_start: int
    ts_end: int
    # Matches the snake_case `name` discriminator on ExtensionActionRequest
    # (e.g. "go_to_url", "get_screenshot"). Carried as a plain string rather
    # than a Literal so adding a new extension action in the future does not
    # require a parse-time migration of historical trace data.
    action_name: str
    request_summary: dict[str, Any]
    result_summary: dict[str, Any] | None = None
    status: Literal["success", "error", "timeout"]
    error_message: str | None = None

    @model_validator(mode="after")
    def _check_ts_ordering(self) -> PythonExtensionActionEvent:
        if self.ts_end < self.ts_start:
            raise ValueError(
                f"PythonExtensionActionEvent: ts_end ({self.ts_end}) must be >= ts_start ({self.ts_start})"
            )
        return self


class PythonSideEffectEvent(BaseModel):
    kind: Literal["sideEffect"] = "sideEffect"
    ts: int
    effect_type: Literal["download_file", "render_html"]
    description: str


PythonTraceEvent = Annotated[
    PythonStdoutEvent
    | PythonStderrEvent
    | PythonSubAgentCallEvent
    | PythonExtensionActionEvent
    | PythonSideEffectEvent,
    Field(discriminator="kind"),
]


class PythonAgentRunTrace(BaseModel):
    step_type: Literal["pythonAgentRun"] = "pythonAgentRun"
    url: str
    status: Literal["success", "error", "aborted"]
    duration_ms: NonNegativeInt
    events: list[PythonTraceEvent]
    error_message: str | None = None


ApaStepTrace = Annotated[
    GoToUrlTrace
    | GetUrlTrace
    | PrintTrace
    | AgentTrace
    | ForLoopTrace
    | WhileLoopTrace
    | AgenticSelectorTrace
    | AgenticMouseActionTrace
    | WaitForElementTrace
    | PressKeysTrace
    | ReadCsvTrace
    | ReadGoogleSheetTrace
    | WriteGoogleSheetTrace
    | DataTableExportAsCsvTrace
    | ObjectExportAsJsonTrace
    | PythonTrace
    | StartTrace
    | EndTrace
    | GetFullHtmlTrace
    | GetSimplifiedHtmlTrace
    | GetScreenshotTrace
    | RunCustomAgentTrace
    | IfTrace
    | SetVariableTrace
    | WaitTrace
    | DataTableInsertRowTrace
    | DataTableUpdateCellValueTrace
    | ObjectSetPropertiesTrace
    | OutputTrace
    | PythonAgentRunTrace,
    Field(discriminator="step_type"),
]

type OperatorActionTrace = list[OperatorActionTraceItem]
type ApaActionTrace = list[ApaStepTrace]
type ActionTrace = OperatorActionTrace | ApaActionTrace


_OperatorActionTraceAdapter = TypeAdapter(OperatorActionTrace)
_ApaActionTraceAdapter = TypeAdapter(ApaActionTrace)


def parse_action_trace(trace_data: list[dict[str, Any] | Any]) -> ActionTrace:
    """Parse the action trace.

    Dispatches deterministically based on the shape of the first item rather
    than try/except-falling-through two adapters: operator items carry
    ``action`` + ``url`` fields, APA steps carry ``step_type``. On an empty
    list (no discriminator available) we default to APA, which is the
    superset shape used by all custom agents.
    """
    if not trace_data:
        return _ApaActionTraceAdapter.validate_python(trace_data)

    first = trace_data[0]
    if isinstance(first, dict) and "step_type" in first:
        return _ApaActionTraceAdapter.validate_python(trace_data)
    if isinstance(first, dict) and "action" in first and "url" in first:
        return _OperatorActionTraceAdapter.validate_python(trace_data)

    # Ambiguous shape — fall back to the previous try/except pattern so we
    # do not regress existing callers passing Pydantic instances or other
    # shapes the adapters already know how to coerce.
    try:
        return _OperatorActionTraceAdapter.validate_python(trace_data)
    except ValidationError:
        return _ApaActionTraceAdapter.validate_python(trace_data)


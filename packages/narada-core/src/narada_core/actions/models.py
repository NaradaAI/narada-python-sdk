from __future__ import annotations

from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    NotRequired,
    TypedDict,
    TypeVar,
    cast,
    override,
)

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

# There is no `AgentRequest` because the `agent` action delegates to the `dispatch_request` method
# under the hood.

_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class AgentUsage(BaseModel):
    actions: int
    credits: int


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
    | ObjectSetPropertiesTrace,
    Field(discriminator="step_type"),
]

type OperatorActionTrace = list[OperatorActionTraceItem]
type ApaActionTrace = list[ApaStepTrace]
type ActionTrace = OperatorActionTrace | ApaActionTrace


# TypeAdapter for parsing discriminated union
_OperatorActionTraceAdapter = TypeAdapter(OperatorActionTrace)
_ApaActionTraceAdapter = TypeAdapter(ApaActionTrace)


def parse_action_trace(trace_data: list[dict[str, Any] | Any]) -> ActionTrace:
    """Parse the action trace, it will either be a list of operator action trace items or a list of APA action trace items."""
    try:
        return _OperatorActionTraceAdapter.validate_python(trace_data)
    except ValidationError:
        return _ApaActionTraceAdapter.validate_python(trace_data)


class AgentResponse(BaseModel, Generic[_MaybeStructuredOutput]):
    request_id: str
    status: Literal["success", "error", "input-required"]
    text: str
    structured_output: _MaybeStructuredOutput | None
    usage: AgentUsage
    action_trace: ActionTrace | None = None


class AgenticSelectorClickAction(TypedDict):
    type: Literal["click"]


class AgenticSelectorRightClickAction(TypedDict):
    type: Literal["right_click"]


class AgenticSelectorDoubleClickAction(TypedDict):
    type: Literal["double_click"]


class AgenticSelectorHoverAction(TypedDict):
    type: Literal["hover"]


class AgenticSelectorFillAction(TypedDict):
    type: Literal["fill"]
    value: str


class AgenticSelectorSelectOptionByIndexAction(TypedDict):
    type: Literal["select_option_by_index"]
    value: int


class AgenticSelectorSelectOptionByValueAction(TypedDict):
    type: Literal["select_option_by_value"]
    value: str


class AgenticSelectorGetTextAction(TypedDict):
    type: Literal["get_text"]


class AgenticSelectorGetPropertyAction(TypedDict):
    type: Literal["get_property"]
    property_name: str


AgenticSelectorAction = (
    AgenticSelectorClickAction
    | AgenticSelectorRightClickAction
    | AgenticSelectorDoubleClickAction
    | AgenticSelectorHoverAction
    | AgenticSelectorFillAction
    | AgenticSelectorSelectOptionByIndexAction
    | AgenticSelectorSelectOptionByValueAction
    | AgenticSelectorGetTextAction
    | AgenticSelectorGetPropertyAction
)


def _dump_agentic_selector_action(action: AgenticSelectorAction) -> dict[str, Any]:
    match action["type"]:
        case "click":
            return cast(dict[str, Any], action)
        case "right_click":
            return {"type": "rightClick"}
        case "double_click":
            return {"type": "doubleClick"}
        case "hover":
            return {"type": "hover"}
        case "fill":
            return cast(dict[str, Any], action)
        case "select_option_by_index":
            return {"type": "selectOptionByIndex", "value": action["value"]}
        case "select_option_by_value":
            return {"type": "selectOptionByValue", "value": action["value"]}
        case "get_text":
            return {"type": "getText"}
        case "get_property":
            return {
                "type": "getProperty",
                "propertyName": action["property_name"],
            }


class AgenticSelectors(TypedDict, total=False):
    id: str
    data_testid: str
    name: str
    aria_label: str
    role: str
    type: str
    text_content: str
    tag_name: str
    class_name: str
    dom_path: str
    xpath: str


def _dump_agentic_selectors(selectors: AgenticSelectors) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if id := selectors.get("id"):
        result["id"] = {"value": id}
    if data_testid := selectors.get("data_testid"):
        result["dataTestId"] = {"value": data_testid}
    if name := selectors.get("name"):
        result["name"] = {"value": name}
    if aria_label := selectors.get("aria_label"):
        result["ariaLabel"] = {"value": aria_label}
    if role := selectors.get("role"):
        result["role"] = {"value": role}
    if type := selectors.get("type"):
        result["type"] = {"value": type}
    if text_content := selectors.get("text_content"):
        result["textContent"] = {"value": text_content}
    if tag_name := selectors.get("tag_name"):
        result["tagName"] = {"value": tag_name}
    if class_name := selectors.get("class_name"):
        result["className"] = {"value": class_name}
    if dom_path := selectors.get("dom_path"):
        result["domPath"] = {"value": dom_path}
    if xpath := selectors.get("xpath"):
        result["xpath"] = {"value": xpath}
    return result


class AgenticSelectorRequest(BaseModel):
    name: Literal["agentic_selector"] = "agentic_selector"
    action: AgenticSelectorAction
    selectors: AgenticSelectors
    fallback_operator_query: str

    @override
    def model_dump(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "action": _dump_agentic_selector_action(self.action),
            "selectors": _dump_agentic_selectors(self.selectors),
            "fallback_operator_query": self.fallback_operator_query,
        }


class AgenticSelectorResponse(BaseModel):
    value: str | None


class Viewport(TypedDict):
    width: int
    height: int


class RecordedClick(TypedDict):
    x: int
    y: int
    viewport: Viewport


class AgenticMouseClickAction(TypedDict):
    type: Literal["click"]


class AgenticMouseRightClickAction(TypedDict):
    type: Literal["right_click"]


class AgenticMouseDoubleClickAction(TypedDict):
    type: Literal["double_click"]


class AgenticMouseFillAction(TypedDict):
    type: Literal["fill"]
    text: str
    press_enter: NotRequired[bool]


class AgenticMouseScrollAction(TypedDict):
    type: Literal["scroll"]
    horizontal: int
    vertical: int


AgenticMouseAction = (
    AgenticMouseClickAction
    | AgenticMouseRightClickAction
    | AgenticMouseDoubleClickAction
    | AgenticMouseFillAction
    | AgenticMouseScrollAction
)


def _dump_agentic_mouse_action(action: AgenticMouseAction) -> dict[str, Any]:
    match action["type"]:
        case "click":
            return {"type": "click"}
        case "right_click":
            return {"type": "rightClick"}
        case "double_click":
            return {"type": "doubleClick"}
        case "fill":
            return {
                "type": "fill",
                "text": action["text"],
                "pressEnter": action.get("press_enter", False),
            }
        case "scroll":
            return {
                "type": "scroll",
                "deltaX": action["horizontal"],
                "deltaY": action["vertical"],
            }


class AgenticMouseActionRequest(BaseModel):
    name: Literal["agentic_mouse_action"] = "agentic_mouse_action"
    action: AgenticMouseAction
    recorded_click: RecordedClick
    fallback_operator_query: str
    resize_window: bool = False

    @override
    def model_dump(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "action": _dump_agentic_mouse_action(self.action),
            "recorded_click": self.recorded_click,
            "resize_window": self.resize_window,
            "fallback_operator_query": self.fallback_operator_query,
        }


class CloseWindowRequest(BaseModel):
    name: Literal["close_window"] = "close_window"


class GoToUrlRequest(BaseModel):
    name: Literal["go_to_url"] = "go_to_url"
    url: str
    new_tab: bool


class PrintMessageRequest(BaseModel):
    name: Literal["print_message"] = "print_message"
    message: str


class ReadGoogleSheetRequest(BaseModel):
    name: Literal["read_google_sheet"] = "read_google_sheet"
    spreadsheet_id: str
    range: str


class ReadGoogleSheetResponse(BaseModel):
    values: list[list[str]]


class WriteGoogleSheetRequest(BaseModel):
    name: Literal["write_google_sheet"] = "write_google_sheet"
    spreadsheet_id: str
    range: str
    values: list[list[str]]


class GetFullHtmlRequest(BaseModel):
    name: Literal["get_full_html"] = "get_full_html"


class GetFullHtmlResponse(BaseModel):
    html: str


class GetSimplifiedHtmlRequest(BaseModel):
    name: Literal["get_simplified_html"] = "get_simplified_html"


class GetSimplifiedHtmlResponse(BaseModel):
    html: str


class GetScreenshotRequest(BaseModel):
    name: Literal["get_screenshot"] = "get_screenshot"


class GetScreenshotResponse(BaseModel):
    base64_content: str
    name: str
    mime_type: str
    timestamp: str


class GetUrlRequest(BaseModel):
    name: Literal["get_url"] = "get_url"


class GetUrlResponse(BaseModel):
    url: str


type ExtensionActionRequest = (
    AgenticSelectorRequest
    | AgenticMouseActionRequest
    | CloseWindowRequest
    | GoToUrlRequest
    | PrintMessageRequest
    | ReadGoogleSheetRequest
    | WriteGoogleSheetRequest
    | GetFullHtmlRequest
    | GetSimplifiedHtmlRequest
    | GetScreenshotRequest
    | GetUrlRequest
)


class ExtensionActionResponse(BaseModel):
    status: Literal["success", "error"]
    error: str | None = None
    data: str | None = None

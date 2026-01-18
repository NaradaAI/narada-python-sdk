from typing import (
    Any,
    Generic,
    Literal,
    TypedDict,
    NotRequired,
    TypeVar,
    cast,
    override,
)

from pydantic import BaseModel, Field

# There is no `AgentRequest` because the `agent` action delegates to the `dispatch_request` method
# under the hood.

_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class AgentUsage(BaseModel):
    actions: int
    credits: int


class ActionTraceItem(BaseModel):
    url: str
    action: str


# Individual trace types for apaTrace - Pydantic models for parsing
class GoToUrlTrace(BaseModel):
    step_type: Literal["goToUrl"] = Field(alias="stepType")
    url: str
    description: str


class PrintTrace(BaseModel):
    step_type: Literal["print"] = Field(alias="stepType")
    url: str
    message: str


class AgentTrace(BaseModel):
    step_type: Literal["agent"] = Field(alias="stepType")
    url: str
    agent_type: str = Field(alias="agentType")
    action_trace: list[ActionTraceItem] | None = Field(None, alias="actionTrace")
    text: str | None = None


class ForLoopTrace(BaseModel):
    step_type: Literal["for"] = Field(alias="stepType")
    url: str
    loop_type: Literal["nTimes", "forEachRowInDataTable", "forEachItemsInArray"] = (
        Field(alias="loopType")
    )
    description: str
    iterations: list[list["ApaTraceItem"]]  # Recursive reference


class WhileLoopTrace(BaseModel):
    step_type: Literal["while"] = Field(alias="stepType")
    url: str
    condition: str
    iterations: list[list["ApaTraceItem"]]  # Recursive reference
    total_iterations: int = Field(alias="totalIterations")


class AgenticSelectorTrace(BaseModel):
    step_type: Literal["agenticSelector"] = Field(alias="stepType")
    url: str
    description: str
    action_trace: list[ActionTraceItem] | None = Field(None, alias="actionTrace")


class AgenticMouseActionTrace(BaseModel):
    step_type: Literal["agenticMouseAction"] = Field(alias="stepType")
    url: str
    description: str
    action_trace: list[ActionTraceItem] | None = Field(None, alias="actionTrace")


class WaitForElementTrace(BaseModel):
    step_type: Literal["waitForElement"] = Field(alias="stepType")
    url: str
    description: str


class PressKeysTrace(BaseModel):
    step_type: Literal["pressKeys"] = Field(alias="stepType")
    url: str
    description: str


class ReadGoogleSheetTrace(BaseModel):
    step_type: Literal["readGoogleSheet"] = Field(alias="stepType")
    url: str
    description: str


class WriteGoogleSheetTrace(BaseModel):
    step_type: Literal["writeGoogleSheet"] = Field(alias="stepType")
    url: str
    description: str


class DataTableExportAsCsvTrace(BaseModel):
    step_type: Literal["dataTableExportAsCsv"] = Field(alias="stepType")
    url: str
    description: str


class PythonTrace(BaseModel):
    step_type: Literal["python"] = Field(alias="stepType")
    url: str
    description: str


class ReadCsvTrace(BaseModel):
    step_type: Literal["readCsv"] = Field(alias="stepType")
    url: str
    description: str


class StartTrace(BaseModel):
    step_type: Literal["start"] = Field(alias="stepType")
    url: str
    description: str


class EndTrace(BaseModel):
    step_type: Literal["end"] = Field(alias="stepType")
    url: str
    description: str


class GetFullHtmlTrace(BaseModel):
    step_type: Literal["getFullHtml"] = Field(alias="stepType")
    url: str
    description: str


class GetSimplifiedHtmlTrace(BaseModel):
    step_type: Literal["getSimplifiedHtml"] = Field(alias="stepType")
    url: str
    description: str


class GetScreenshotTrace(BaseModel):
    step_type: Literal["getScreenshot"] = Field(alias="stepType")
    url: str
    description: str


# Union type for all trace types
ApaTraceItem = (
    GoToUrlTrace
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
    | PythonTrace
    | StartTrace
    | EndTrace
    | GetFullHtmlTrace
    | GetSimplifiedHtmlTrace
    | GetScreenshotTrace
)


def _parse_apa_trace_item(data: dict[str, Any]) -> ApaTraceItem:
    """Parse a single apaTrace item based on its stepType."""
    step_type = data.get("stepType")
    if not isinstance(step_type, str):
        raise ValueError(f"Invalid stepType: {step_type}")

    # Map stepType to the appropriate model
    trace_classes: dict[str, type[BaseModel]] = {
        "goToUrl": GoToUrlTrace,
        "print": PrintTrace,
        "agent": AgentTrace,
        "for": ForLoopTrace,
        "while": WhileLoopTrace,
        "agenticSelector": AgenticSelectorTrace,
        "agenticMouseAction": AgenticMouseActionTrace,
        "waitForElement": WaitForElementTrace,
        "pressKeys": PressKeysTrace,
        "readCsv": ReadCsvTrace,
        "readGoogleSheet": ReadGoogleSheetTrace,
        "writeGoogleSheet": WriteGoogleSheetTrace,
        "dataTableExportAsCsv": DataTableExportAsCsvTrace,
        "python": PythonTrace,
        "start": StartTrace,
        "end": EndTrace,
        "getFullHtml": GetFullHtmlTrace,
        "getSimplifiedHtml": GetSimplifiedHtmlTrace,
        "getScreenshot": GetScreenshotTrace,
    }

    trace_class = trace_classes.get(step_type)
    if trace_class is None:
        raise ValueError(f"Unknown stepType: {step_type}")

    # Handle recursive types (for loops and while loops)
    if step_type in ("for", "while") and "iterations" in data:
        # Recursively parse iterations - create a copy to avoid mutating original
        parsed_data = data.copy()
        parsed_iterations = []
        for iteration in data["iterations"]:
            parsed_iteration = [_parse_apa_trace_item(item) for item in iteration]
            parsed_iterations.append(parsed_iteration)
        parsed_data["iterations"] = parsed_iterations
        result = trace_class.model_validate(parsed_data)
        return cast(ApaTraceItem, result)

    result = trace_class.model_validate(data)
    return cast(ApaTraceItem, result)


def parse_apa_trace(trace_data: list[dict[str, Any] | Any]) -> list[ApaTraceItem]:
    """Parse a list of apaTrace items."""
    return [_parse_apa_trace_item(cast(dict[str, Any], item)) for item in trace_data]


class AgentResponse(BaseModel, Generic[_MaybeStructuredOutput]):
    request_id: str
    status: Literal["success", "error", "input-required"]
    text: str
    structured_output: _MaybeStructuredOutput | None
    usage: AgentUsage
    action_trace: list[ActionTraceItem] | None = None
    apa_trace: list[ApaTraceItem] | None = None


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
                "propertyName": action["property_name"].value,
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
)


class ExtensionActionResponse(BaseModel):
    status: Literal["success", "error"]
    error: str | None = None
    data: str | None = None

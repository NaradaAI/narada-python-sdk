from enum import Enum
from typing import (
    Any,
    Generic,
    Literal,
    Optional,
    TypedDict,
    NotRequired,
    TypeVar,
    cast,
    override,
)

from pydantic import BaseModel

# There is no `AgentRequest` because the `agent` action delegates to the `dispatch_request` method
# under the hood.

_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class AgentUsage(BaseModel):
    actions: int
    credits: int


class AgentResponse(BaseModel, Generic[_MaybeStructuredOutput]):
    request_id: str
    status: Literal["success", "error", "input-required"]
    text: str
    structured_output: _MaybeStructuredOutput | None
    usage: AgentUsage


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


class PropertyName(str, Enum):
    VALUE = "value"
    CHECKED = "checked"
    HREF = "href"
    SRC = "src"
    ID = "id"
    CLASSNAME = "className"
    TAG_NAME = "tagName"
    INNER_HTML = "innerHTML"
    DISABLED = "disabled"
    HIDDEN = "hidden"
    READONLY = "readOnly"
    REQUIRED = "required"
    SELECTED_INDEX = "selectedIndex"
    OFFSET_WIDTH = "offsetWidth"
    OFFSET_HEIGHT = "offsetHeight"
    SCROLL_TOP = "scrollTop"
    SCROLL_LEFT = "scrollLeft"


class AgenticSelectorGetPropertyAction(TypedDict):
    type: Literal["get_property"]
    property_name: PropertyName


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


class RecordedClick(TypedDict):
    x: int
    y: int
    width: int
    height: int


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


def _dump_recorded_click(recorded_click: RecordedClick) -> dict[str, Any]:
    return {
        "x": recorded_click["x"],
        "y": recorded_click["y"],
        "viewport": {
            "width": recorded_click["width"],
            "height": recorded_click["height"],
        },
    }


class AgenticMouseActionRequest(BaseModel):
    name: Literal["agentic_mouse_action"] = "agentic_mouse_action"
    action: AgenticMouseAction
    recorded_click: RecordedClick
    resize_window: Optional[bool] = False
    fallback_operator_query: str

    @override
    def model_dump(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "action": _dump_agentic_mouse_action(self.action),
            "recorded_click": _dump_recorded_click(self.recorded_click),
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


type ExtensionActionRequest = (
    AgenticSelectorRequest
    | AgenticMouseActionRequest
    | CloseWindowRequest
    | GoToUrlRequest
    | PrintMessageRequest
    | ReadGoogleSheetRequest
    | WriteGoogleSheetRequest
)


class ExtensionActionResponse(BaseModel):
    status: Literal["success", "error"]
    error: str | None = None
    data: str | None = None

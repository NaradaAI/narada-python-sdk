from typing import Any, Generic, Literal, TypedDict, TypeVar, cast, override

from pydantic import BaseModel

# There is no `AgentRequest` because the `agent` action delegates to the `dispatch_request` method
# under the hood.

_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class AgentUsage(BaseModel):
    actions: int
    credits: int


class AgentResponse(BaseModel, Generic[_MaybeStructuredOutput]):
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


class AgenticSelectorFillAction(TypedDict):
    type: Literal["fill"]
    value: str


class AgenticSelectorSelectOptionByIndexAction(TypedDict):
    type: Literal["select_option_by_index"]
    index: int


type AgenticSelectorAction = (
    AgenticSelectorClickAction
    | AgenticSelectorRightClickAction
    | AgenticSelectorDoubleClickAction
    | AgenticSelectorFillAction
    | AgenticSelectorSelectOptionByIndexAction
)


def _dump_agentic_selector_action(action: AgenticSelectorAction) -> dict[str, Any]:
    match action["type"]:
        case "click":
            return cast(dict[str, Any], action)
        case "right_click":
            return {"type": "rightClick"}
        case "double_click":
            return {"type": "doubleClick"}
        case "fill":
            return cast(dict[str, Any], action)
        case "select_option_by_index":
            return {"type": "selectOptionByIndex", "value": action["index"]}


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

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

# There is no `AgentRequest` because the `agent` action delegates to the `dispatch_request` method
# under the hood.

_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class AgentResponse(BaseModel, Generic[_MaybeStructuredOutput]):
    status: Literal["success", "error", "input-required"]
    text: str
    structured_output: _MaybeStructuredOutput | None


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
    GoToUrlRequest
    | PrintMessageRequest
    | ReadGoogleSheetRequest
    | WriteGoogleSheetRequest
)


class ExtensionActionResponse(BaseModel):
    status: Literal["success", "error"]
    error: str | None = None
    data: str | None = None

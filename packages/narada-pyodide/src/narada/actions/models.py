from abc import ABC
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel


class BaseExtensionActionResponse(ABC, BaseModel):
    status: Literal["success", "error"]
    error: str | None = None


# There is no `AgentRequest` because the `agent` action delegates to the `dispatch_request` method
# under the hood.

_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class AgentResponse(BaseExtensionActionResponse, Generic[_MaybeStructuredOutput]):
    text: str
    structured_output: _MaybeStructuredOutput | None


class GoToUrlRequest(BaseModel):
    name: Literal["go_to_url"] = "go_to_url"
    url: str
    new_tab: bool


class GoToUrlResponse(BaseExtensionActionResponse):
    pass


class PrintMessageRequest(BaseModel):
    name: Literal["print_message"] = "print_message"
    message: str


class PrintMessageResponse(BaseExtensionActionResponse):
    pass


class ReadGoogleSheetRequest(BaseModel):
    name: Literal["read_google_sheet"] = "read_google_sheet"
    spreadsheet_id: str
    range: str


class ReadGoogleSheetResponse(BaseExtensionActionResponse):
    values: list[list[str]]


class WriteGoogleSheetRequest(BaseModel):
    name: Literal["write_google_sheet"] = "write_google_sheet"
    spreadsheet_id: str
    range: str
    values: list[list[str]]


class WriteGoogleSheetResponse(BaseExtensionActionResponse):
    pass


type ExtensionActionRequest = (
    GoToUrlRequest
    | PrintMessageRequest
    | ReadGoogleSheetRequest
    | WriteGoogleSheetRequest
)

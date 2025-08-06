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


class GoToUrlResponse(BaseExtensionActionResponse):
    pass


class PrintMessageRequest(BaseModel):
    name: Literal["print_message"] = "print_message"
    message: str


class PrintMessageResponse(BaseExtensionActionResponse):
    pass


ExtensionActionRequest = GoToUrlRequest | PrintMessageRequest

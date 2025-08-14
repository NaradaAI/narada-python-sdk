"""Core models and enums for Narada SDK."""

from enum import Enum
from typing import Generic, Literal, TypedDict, TypeVar

from pydantic import BaseModel

# Type variables for generic response handling
_StructuredOutput = TypeVar("_StructuredOutput", bound=BaseModel)
_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)
_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


class ResponseContent(TypedDict, Generic[_MaybeStructuredOutput]):
    """Response content structure."""

    text: str
    structuredOutput: _MaybeStructuredOutput


class Usage(TypedDict):
    """API usage information."""

    actions: int
    credits: int


class Response(TypedDict, Generic[_MaybeStructuredOutput]):
    """Standard API response structure."""

    requestId: str
    status: Literal["success", "error", "input-required"]
    response: ResponseContent[_MaybeStructuredOutput] | None
    createdAt: str
    completedAt: str | None
    usage: Usage


class Agent(Enum):
    """Available agent types."""

    GENERALIST = 1
    OPERATOR = 2

    def prompt_prefix(self) -> str:
        """Get the prompt prefix for this agent type."""
        match self:
            case Agent.GENERALIST:
                return ""
            case Agent.OPERATOR:
                return "/Operator "


class UserResourceCredentials(TypedDict, total=False):
    """User credentials for external resources."""

    salesforce: dict[str, str]
    jira: dict[str, str]


class RemoteDispatchChatHistoryItem(TypedDict):
    """Chat history item for remote dispatch."""

    role: Literal["user", "assistant"]
    content: str

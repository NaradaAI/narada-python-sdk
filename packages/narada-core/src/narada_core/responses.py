"""Core response models and types for Narada SDK."""

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

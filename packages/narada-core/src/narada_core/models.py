from enum import Enum
from typing import Generic, Literal, NotRequired, TypedDict, TypeVar

from pydantic import BaseModel


class Agent(Enum):
    GENERALIST = 1
    OPERATOR = 2

    def prompt_prefix(self) -> str:
        match self:
            case Agent.GENERALIST:
                return ""
            case Agent.OPERATOR:
                return "/Operator "


class UserResourceCredentials(TypedDict, total=False):
    salesforce: dict[str, str]
    jira: dict[str, str]


class RemoteDispatchChatHistoryItem(TypedDict):
    role: Literal["user", "assistant"]
    content: str


_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class ResponseContent(TypedDict, Generic[_MaybeStructuredOutput]):
    text: str
    structuredOutput: _MaybeStructuredOutput
    actionTrace: NotRequired[str]


class Usage(TypedDict):
    actions: int
    credits: int


class Response(TypedDict, Generic[_MaybeStructuredOutput]):
    requestId: str
    status: Literal["success", "error"]
    response: ResponseContent[_MaybeStructuredOutput] | None
    createdAt: str
    completedAt: str | None
    usage: Usage


class File(TypedDict):
    key: str


############################################################
# Internal models. Do not use these if you're an end user. #
############################################################

type _PackageName = Literal["narada", "narada-pyodide"]


class _PackageConfig(BaseModel):
    min_required_version: str


class _SdkConfig(BaseModel):
    packages: dict[_PackageName, _PackageConfig]

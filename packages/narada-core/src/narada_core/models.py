from enum import Enum, StrEnum
from typing import Annotated, Generic, Literal, NotRequired, TypedDict, TypeVar

from pydantic import BaseModel, Field


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


class AuthenticationType(StrEnum):
    NONE = "none"
    BEARER_TOKEN = "bearer-token"
    CUSTOM_HEADERS = "custom-headers"


class CustomHeader(BaseModel):
    key: str
    value: str


class AuthenticationNone(BaseModel):
    type: Literal[AuthenticationType.NONE] = AuthenticationType.NONE


class AuthenticationBearerToken(BaseModel):
    type: Literal[AuthenticationType.BEARER_TOKEN] = AuthenticationType.BEARER_TOKEN
    bearerToken: str


class AuthenticationCustomHeaders(BaseModel):
    type: Literal[AuthenticationType.CUSTOM_HEADERS] = AuthenticationType.CUSTOM_HEADERS
    customHeaders: list[CustomHeader]


Authentication = Annotated[
    AuthenticationNone | AuthenticationBearerToken | AuthenticationCustomHeaders,
    Field(discriminator="type"),
]


class McpServer(BaseModel):
    url: str
    label: str | None = None
    description: str | None = None
    authentication: Authentication
    selectedTools: list[str] | None = None


class RemoteDispatchChatHistoryItem(TypedDict):
    role: Literal["user", "assistant"]
    content: str


_MaybeStructuredOutput = TypeVar("_MaybeStructuredOutput", bound=BaseModel | None)


class ActionTraceItemTypedDict(TypedDict):
    url: str
    action: str


class ResponseContent(TypedDict, Generic[_MaybeStructuredOutput]):
    text: str
    structuredOutput: _MaybeStructuredOutput
    actionTrace: NotRequired[list[ActionTraceItemTypedDict]]


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

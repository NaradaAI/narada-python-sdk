from __future__ import annotations

from enum import Enum, StrEnum
from typing import Annotated, Generic, Literal, NotRequired, TypedDict, TypeVar

from pydantic import BaseModel, Field


class Agent(Enum):
    GENERALIST = 1
    OPERATOR = 2
    CORE_AGENT = 3

    def prompt_prefix(self) -> str:
        match self:
            case Agent.GENERALIST:
                return ""
            case Agent.OPERATOR:
                return "/Operator "
            case Agent.CORE_AGENT:
                return "/coreAgent "


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


class OperatorActionTraceItem(TypedDict):
    url: str
    action: str


class GoToUrlTrace(TypedDict):
    step_type: Literal["goToUrl"]
    url: str
    description: str


class GetUrlTrace(TypedDict):
    step_type: Literal["getUrl"]
    url: str
    description: str


class PrintTrace(TypedDict):
    step_type: Literal["print"]
    url: str
    message: str


class AgentTrace(TypedDict):
    step_type: Literal["agent"]
    url: str
    agent_type: str  # e.g., 'operator', 'generalist', 'coreAgent', etc.
    action_trace: ActionTrace
    text: str  # For non-operator agents


class ForLoopTrace(TypedDict):
    step_type: Literal["for"]
    url: str
    loop_type: Literal["nTimes", "forEachRowInDataTable", "forEachItemsInArray"]
    description: str
    iterations: list[APAActionTrace]


class WhileLoopTrace(TypedDict):
    step_type: Literal["while"]
    url: str
    condition: str
    iterations: list[APAActionTrace]
    total_iterations: int


class AgenticSelectorTrace(TypedDict):
    step_type: Literal["agenticSelector"]
    url: str
    description: str
    action_trace: ActionTrace  # For operator agent fallback


class AgenticMouseActionTrace(TypedDict):
    step_type: Literal["agenticMouseAction"]
    url: str
    description: str
    action_trace: ActionTrace  # For operator agent fallback


class WaitForElementTrace(TypedDict):
    step_type: Literal["waitForElement"]
    url: str
    description: str


class PressKeysTrace(TypedDict):
    step_type: Literal["pressKeys"]
    url: str
    description: str


class ReadGoogleSheetTrace(TypedDict):
    step_type: Literal["readGoogleSheet"]
    url: str
    description: str


class WriteGoogleSheetTrace(TypedDict):
    step_type: Literal["writeGoogleSheet"]
    url: str
    description: str


class DataTableExportAsCsvTrace(TypedDict):
    step_type: Literal["dataTableExportAsCsv"]
    url: str
    description: str


class PythonTrace(TypedDict):
    step_type: Literal["python"]
    url: str
    description: str


class ReadCsvTrace(TypedDict):
    step_type: Literal["readCsv"]
    url: str
    description: str


class StartTrace(TypedDict):
    step_type: Literal["start"]
    url: str
    description: str


class EndTrace(TypedDict):
    step_type: Literal["end"]
    url: str
    description: str


class GetFullHtmlTrace(TypedDict):
    step_type: Literal["getFullHtml"]
    url: str
    description: str


class GetSimplifiedHtmlTrace(TypedDict):
    step_type: Literal["getSimplifiedHtml"]
    url: str
    description: str


class GetScreenshotTrace(TypedDict):
    step_type: Literal["getScreenshot"]
    url: str
    description: str


class ObjectExportAsJsonTrace(TypedDict):
    step_type: Literal["objectExportAsJson"]
    url: str
    description: str


class RunCustomAgentTrace(TypedDict):
    step_type: Literal["runCustomAgent"]
    url: str
    workflow_id: str
    workflow_name: str
    status: Literal["success", "error"]
    error_message: NotRequired[str]


class IfTrace(TypedDict):
    step_type: Literal["if"]
    url: str
    description: str


class SetVariableTrace(TypedDict):
    step_type: Literal["setVariable"]
    url: str
    description: str


class WaitTrace(TypedDict):
    step_type: Literal["wait"]
    url: str
    description: str


class DataTableInsertRowTrace(TypedDict):
    step_type: Literal["dataTableInsertRow"]
    url: str
    description: str


class DataTableUpdateCellValueTrace(TypedDict):
    step_type: Literal["dataTableUpdateCellValue"]
    url: str
    description: str


class ObjectSetPropertiesTrace(TypedDict):
    step_type: Literal["objectSetProperties"]
    url: str
    description: str


ApaStepTrace = (
    GoToUrlTrace
    | GetUrlTrace
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
    | ObjectExportAsJsonTrace
    | PythonTrace
    | StartTrace
    | EndTrace
    | GetFullHtmlTrace
    | GetSimplifiedHtmlTrace
    | GetScreenshotTrace
    | RunCustomAgentTrace
    | IfTrace
    | SetVariableTrace
    | WaitTrace
    | DataTableInsertRowTrace
    | DataTableUpdateCellValueTrace
    | ObjectSetPropertiesTrace
)


type OperatorActionTrace = list[OperatorActionTraceItem]
type APAActionTrace = list[ApaStepTrace]
type ActionTrace = OperatorActionTrace | APAActionTrace


class ResponseContent(TypedDict, Generic[_MaybeStructuredOutput]):
    text: str
    structuredOutput: _MaybeStructuredOutput
    actionTrace: NotRequired[ActionTrace]


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

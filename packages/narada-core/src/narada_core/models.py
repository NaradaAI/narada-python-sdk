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


class ActionTraceItemTypedDict(TypedDict):
    url: str
    action: str


# Individual trace types for apaTrace - each mirrors the TypeScript structure
class GoToUrlTraceTypedDict(TypedDict):
    stepType: Literal["goToUrl"]
    url: str
    description: str


class PrintTraceTypedDict(TypedDict):
    stepType: Literal["print"]
    url: str
    message: str


class AgentTraceTypedDict(TypedDict, total=False):
    stepType: Literal["agent"]
    url: str
    agentType: str  # e.g., 'operator', 'generalist', 'coreAgent', etc.
    actionTrace: list[ActionTraceItemTypedDict]  # For operator agents
    text: str  # For non-operator agents


class ForLoopTraceTypedDict(TypedDict):
    stepType: Literal["for"]
    url: str
    loopType: Literal["nTimes", "forEachRowInDataTable", "forEachItemsInArray"]
    description: str
    iterations: list[list["ApaTraceItemTypedDict"]]  # Recursive reference


class WhileLoopTraceTypedDict(TypedDict):
    stepType: Literal["while"]
    url: str
    condition: str
    iterations: list[list["ApaTraceItemTypedDict"]]  # Recursive reference
    totalIterations: int


class AgenticSelectorTraceTypedDict(TypedDict, total=False):
    stepType: Literal["agenticSelector"]
    url: str
    description: str
    actionTrace: list[ActionTraceItemTypedDict]  # For operator agent fallback


class AgenticMouseActionTraceTypedDict(TypedDict, total=False):
    stepType: Literal["agenticMouseAction"]
    url: str
    description: str
    actionTrace: list[ActionTraceItemTypedDict]  # For operator agent fallback


class WaitForElementTraceTypedDict(TypedDict):
    stepType: Literal["waitForElement"]
    url: str
    description: str


class PressKeysTraceTypedDict(TypedDict):
    stepType: Literal["pressKeys"]
    url: str
    description: str


class ReadGoogleSheetTraceTypedDict(TypedDict):
    stepType: Literal["readGoogleSheet"]
    url: str
    description: str


class WriteGoogleSheetTraceTypedDict(TypedDict):
    stepType: Literal["writeGoogleSheet"]
    url: str
    description: str


class DataTableExportAsCsvTraceTypedDict(TypedDict):
    stepType: Literal["dataTableExportAsCsv"]
    url: str
    description: str


class PythonTraceTypedDict(TypedDict):
    stepType: Literal["python"]
    url: str
    description: str


class ReadCsvTraceTypedDict(TypedDict):
    stepType: Literal["readCsv"]
    url: str
    description: str


class StartTraceTypedDict(TypedDict):
    stepType: Literal["start"]
    url: str
    description: str


class EndTraceTypedDict(TypedDict):
    stepType: Literal["end"]
    url: str
    description: str


class GetFullHtmlTraceTypedDict(TypedDict):
    stepType: Literal["getFullHtml"]
    url: str
    description: str


class GetSimplifiedHtmlTraceTypedDict(TypedDict):
    stepType: Literal["getSimplifiedHtml"]
    url: str
    description: str


class GetScreenshotTraceTypedDict(TypedDict):
    stepType: Literal["getScreenshot"]
    url: str
    description: str


# Union type for all trace types (mirrors ApaUserFacingTracePart)
ApaTraceItemTypedDict = (
    GoToUrlTraceTypedDict
    | PrintTraceTypedDict
    | AgentTraceTypedDict
    | ForLoopTraceTypedDict
    | WhileLoopTraceTypedDict
    | AgenticSelectorTraceTypedDict
    | AgenticMouseActionTraceTypedDict
    | WaitForElementTraceTypedDict
    | PressKeysTraceTypedDict
    | ReadCsvTraceTypedDict
    | ReadGoogleSheetTraceTypedDict
    | WriteGoogleSheetTraceTypedDict
    | DataTableExportAsCsvTraceTypedDict
    | PythonTraceTypedDict
    | StartTraceTypedDict
    | EndTraceTypedDict
    | GetFullHtmlTraceTypedDict
    | GetSimplifiedHtmlTraceTypedDict
    | GetScreenshotTraceTypedDict
)


class ResponseContent(TypedDict, Generic[_MaybeStructuredOutput]):
    text: str
    structuredOutput: _MaybeStructuredOutput
    actionTrace: NotRequired[list[ActionTraceItemTypedDict]]
    apaTrace: NotRequired[list[ApaTraceItemTypedDict]]


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

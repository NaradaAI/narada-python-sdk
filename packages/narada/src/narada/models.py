from enum import Enum
from typing import Literal, TypedDict


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

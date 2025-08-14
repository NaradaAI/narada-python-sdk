"""Core models and enums for Narada SDK."""

from enum import Enum
from typing import Literal, TypedDict


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

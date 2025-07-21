from pydantic import BaseModel
from typing import Literal, TypeAlias


UserResourceCredentials: TypeAlias = dict[Literal["salesforce", "jira"], dict[str, str]]


class RemoteDispatchChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str

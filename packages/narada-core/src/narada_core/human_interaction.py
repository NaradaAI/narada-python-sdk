from __future__ import annotations

from typing import NotRequired, Protocol, TypedDict

from narada_core.types import InputVariables, InputVariableValue, PromptVariableType


class UserAbortedError(Exception):
    """Raised when a human-in-the-loop interaction is cancelled by the user."""


class PromptVariableRequest(TypedDict):
    name: str
    type: PromptVariableType
    required: bool
    initial_value: NotRequired[InputVariableValue]
    enum_values: NotRequired[list[str]]


class HumanInteractionHandler(Protocol):
    async def request_user_approval(
        self,
        *,
        step_id: str,
        prompt_message: str,
        approve_label: str,
        reject_label: str,
    ) -> bool: ...

    async def prompt_for_user_input(
        self,
        *,
        step_id: str,
        variables: list[PromptVariableRequest],
    ) -> InputVariables: ...

from __future__ import annotations

import asyncio
import json
from typing import Callable

from narada_core.human_interaction import (
    HumanInteractionHandler,
    PromptVariableRequest,
    UserAbortedError,
)
from narada_core.types import InputVariables, InputVariableValue, PromptVariableType


class CliHumanInteractionHandler:
    """CLI-backed optional helper implementation for human interaction prompts."""

    def __init__(self, *, reader: Callable[[str], str] = input) -> None:
        # Injectable reader keeps this class easy to test.
        self._reader = reader

    async def request_user_approval(
        self,
        *,
        step_id: str,
        prompt_message: str,
        approve_label: str,
        reject_label: str,
    ) -> bool:
        prompt = (
            f"[{step_id}] {prompt_message}\n"
            f"Type '{approve_label}' to approve, '{reject_label}' to reject, or 'cancel' to abort: "
        )
        approve_token = approve_label.strip().lower()
        reject_token = reject_label.strip().lower()
        while True:
            value = (await self._read_line(prompt)).strip().lower()
            if value == "cancel":
                raise UserAbortedError("User approval was cancelled.")
            if value == approve_token:
                return True
            if value == reject_token:
                return False

    async def prompt_for_user_input(
        self,
        *,
        step_id: str,
        variables: list[PromptVariableRequest],
    ) -> InputVariables:
        values_by_name: InputVariables = {}
        for variable in variables:
            value = await self._prompt_variable(step_id=step_id, variable=variable)
            if value is not None:
                values_by_name[variable["name"]] = value
        return values_by_name

    async def _prompt_variable(
        self, *, step_id: str, variable: PromptVariableRequest
    ) -> InputVariableValue | None:
        name = variable["name"]
        var_type = variable["type"]
        required = variable["required"]
        has_initial_value = "initial_value" in variable
        initial_value = variable.get("initial_value")
        enum_values = variable.get("enum_values")

        while True:
            base_prompt = f"[{step_id}] Enter value for '{name}' ({var_type})"
            if enum_values:
                base_prompt += f" from {enum_values}"
            if has_initial_value:
                base_prompt += f" [default={json.dumps(initial_value)}]"
            base_prompt += " (or 'cancel' to abort): "

            raw_value = (await self._read_line(base_prompt)).strip()
            if raw_value.lower() == "cancel":
                raise UserAbortedError(
                    f"User input was cancelled at variable '{name}'."
                )

            if raw_value == "":
                if has_initial_value:
                    return initial_value
                if required:
                    continue
                return None

            parsed = self._parse_input_value(
                raw_value=raw_value,
                var_type=var_type,
                enum_values=enum_values,
            )
            if parsed is not None:
                return parsed

    def _parse_input_value(
        self,
        *,
        raw_value: str,
        var_type: PromptVariableType,
        enum_values: list[str] | None,
    ) -> InputVariableValue | None:
        if var_type == "string":
            return raw_value
        if var_type == "enum":
            if enum_values is None:
                return None
            return raw_value if raw_value in enum_values else None

        if var_type in {"number", "boolean", "array", "object", "dataTable"}:
            try:
                parsed = json.loads(raw_value)
            except json.JSONDecodeError:
                return None
            return self._validate_json_value(var_type=var_type, parsed=parsed)

        return None

    def _validate_json_value(
        self, *, var_type: PromptVariableType, parsed: object
    ) -> InputVariableValue | None:
        if var_type == "number":
            return parsed if isinstance(parsed, (int, float)) else None
        if var_type == "boolean":
            return parsed if isinstance(parsed, bool) else None
        if var_type == "array":
            return parsed if isinstance(parsed, list) else None
        if var_type in {"object", "dataTable"}:
            return parsed if isinstance(parsed, (dict, list)) else None
        return None

    async def _read_line(self, prompt: str) -> str:
        try:
            return await asyncio.to_thread(self._reader, prompt)
        except (EOFError, KeyboardInterrupt) as error:
            raise UserAbortedError("User input was cancelled.") from error


__all__ = [
    "CliHumanInteractionHandler",
    "HumanInteractionHandler",
    "PromptVariableRequest",
    "UserAbortedError",
]

from __future__ import annotations

from io import IOBase
from typing import Literal

type JsonPrimitive = str | int | float | bool | None
type InputVariableValue = (
    JsonPrimitive | list["InputVariableValue"] | dict[str, "InputVariableValue"]
)
type InputVariables = dict[str, InputVariableValue]

# Dispatch input variables additionally support file-like values that get uploaded.
type DispatchInputVariableValue = InputVariableValue | IOBase
type DispatchInputVariables = dict[str, DispatchInputVariableValue]

type PromptVariableType = Literal[
    "string",
    "number",
    "boolean",
    "enum",
    "dataTable",
    "object",
    "array",
]

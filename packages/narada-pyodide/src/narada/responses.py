"""Pyodide SDK result types for Operator Memory."""

from typing import Generic, Literal, TypeVar

from narada_core.actions.models import AgentResponse as CoreAgentResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class OperatorMemoryOutcome(BaseModel):
    """Review outcome and whether Memory charges are reflected in the usage total."""

    model_config = ConfigDict(populate_by_name=True)

    outcome: Literal["pending", "reused", "published", "skipped", "failed", "unknown"]
    usage_is_final: StrictBool = Field(alias="usageIsFinal")


_StructuredOutput = TypeVar("_StructuredOutput")


class AgentResponse(CoreAgentResponse[_StructuredOutput], Generic[_StructuredOutput]):
    """Pyodide Agent result with optional Operator Memory settlement."""

    operator_memory: OperatorMemoryOutcome | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

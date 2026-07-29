"""Span records and their common envelope fields."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

from narada_core.tracing.span_data import SpanDataUnion


class SpanError(BaseModel):
    message: str = Field(description="Human-readable description of the span error.")
    data: dict[str, Any] | None = Field(
        description="Structured details associated with the error, or null.",
    )


TSpanData = TypeVar("TSpanData", bound=SpanDataUnion)


class Span(BaseModel, Generic[TSpanData]):
    """A trace span that preserves the concrete type of its span data.

    The type parameter lets callers retain precise access to subtype-specific
    fields, for example ``Span[AgentSpanData].span_data.agent_type``. A
    discriminated union remains available separately for parsing serialized
    span data whose subtype is not known in advance.
    """

    object: Literal["trace.span"] = Field(
        default="trace.span",
        description="Discriminator identifying this record as a span.",
    )
    span_id: str = Field(
        description="Unique identifier for the span.",
    )
    trace_id: str = Field(description="Identifier of the trace containing this span.")
    parent_id: str | None = Field(
        default=None,
        description="Identifier of the parent span, or null for a root span.",
    )
    started_at: str | None = Field(
        default=None,
        description="UTC ISO 8601 timestamp at which the span started.",
    )
    ended_at: str | None = Field(
        default=None,
        description="UTC ISO 8601 timestamp at which the span ended.",
    )
    span_data: TSpanData = Field(
        description="Typed payload describing the operation represented by the span."
    )
    error: SpanError | None = Field(
        default=None,
        description="Error recorded for the span, or null when no error was recorded.",
    )

    @field_validator("started_at", "ended_at")
    @classmethod
    def _require_utc_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("trace timestamps must be ISO 8601 strings") from error
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("trace timestamps must be timezone-aware UTC datetimes")
        return value

    @model_validator(mode="after")
    def _validate_timestamp_order(self) -> Span:
        if (
            self.started_at is not None
            and self.ended_at is not None
            and datetime.fromisoformat(self.ended_at)
            < datetime.fromisoformat(self.started_at)
        ):
            raise ValueError("ended_at must be greater than or equal to started_at")
        return self

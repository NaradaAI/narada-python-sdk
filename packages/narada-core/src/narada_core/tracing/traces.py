"""Top-level trace records."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Trace(BaseModel):
    object: Literal["trace"] = Field(
        default="trace",
        description="Discriminator identifying this record as a trace.",
    )
    trace_id: str = Field(
        description="Unique identifier for the trace.",
    )
    name: str = Field(
        description="Human-readable name of the logical workflow.",
    )
    group_id: str | None = Field(
        default=None,
        description=(
            "Optional caller-supplied identifier used to correlate related traces. "
            "This is distinct from per-run request identifiers."
        ),
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional user-provided metadata associated with the trace.",
    )

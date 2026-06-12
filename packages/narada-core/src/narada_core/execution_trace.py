from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ExecutionTraceContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["executionTraceContext"] = "executionTraceContext"
    schemaVersion: int = 1
    label: str
    traceId: str
    segmentId: str | None = None
    segmentKind: str | None = None
    executionTraceS3Key: str
    executionTraceSegmentS3Key: str | None = None
    rootExecutionTraceS3Key: str | None = None
    status: str | None = None
    summary: dict[str, Any] | None = None

"""Parsing helpers for response trace records."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError

from narada_core.tracing.span_data import SpanDataUnion
from narada_core.tracing.spans import Span
from narada_core.tracing.traces import Trace

logger = logging.getLogger(__name__)

type ResponseTraceRecord = Annotated[
    Trace | Span[SpanDataUnion],
    Field(discriminator="object"),
]

_RESPONSE_TRACE_RECORD_ADAPTER = TypeAdapter(ResponseTraceRecord)


def parse_response_trace(value: Any) -> list[ResponseTraceRecord]:
    """Parse valid records without allowing trace failures to fail an SDK call."""
    if value is None:
        return []
    if not isinstance(value, list):
        logger.warning("Ignoring response trace because it is not a list")
        return []

    records: list[ResponseTraceRecord] = []
    for index, record in enumerate(value):
        try:
            records.append(_RESPONSE_TRACE_RECORD_ADAPTER.validate_python(record))
        except (TypeError, ValidationError, ValueError):
            logger.warning(
                "Ignoring malformed response trace record at index %d", index
            )
    return records

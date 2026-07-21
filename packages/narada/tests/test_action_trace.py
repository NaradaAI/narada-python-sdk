from __future__ import annotations

import pytest
from narada_core.tracing.model import OperatorActionTraceItem, parse_action_trace
from pydantic import ValidationError


def test_parse_operator_action_trace_exposes_timestamps() -> None:
    trace = parse_action_trace(
        [
            {
                "url": "https://example.com",
                "action": "Clicked Submit",
                "startTs": "2026-07-20T17:00:00.000Z",
                "endTs": "2026-07-20T17:00:01.500Z",
            }
        ]
    )

    item = trace[0]
    assert isinstance(item, OperatorActionTraceItem)
    assert item.start_ts == "2026-07-20T17:00:00.000Z"
    assert item.end_ts == "2026-07-20T17:00:01.500Z"


@pytest.mark.parametrize(
    "timestamps",
    [
        {"startTs": "2026-07-20T17:00:00.000Z"},
        {"endTs": "2026-07-20T17:00:01.000Z"},
        {
            "startTs": "2026-07-20T17:00:02.000Z",
            "endTs": "2026-07-20T17:00:01.000Z",
        },
        {
            "startTs": "not-a-timestamp",
            "endTs": "2026-07-20T17:00:01.000Z",
        },
        {
            "startTs": "2026-07-20T17:00:00",
            "endTs": "2026-07-20T17:00:01",
        },
        {"startTs": 1_000, "endTs": 2_000},
    ],
)
def test_operator_action_trace_rejects_invalid_timestamp_ranges(
    timestamps: dict[str, str | int],
) -> None:
    with pytest.raises(ValidationError):
        OperatorActionTraceItem(
            url="https://example.com",
            action="Clicked Submit",
            **timestamps,
        )


def test_operator_action_trace_accepts_explicit_utc_offset() -> None:
    item = OperatorActionTraceItem(
        url="https://example.com",
        action="Clicked Submit",
        startTs="2026-07-20T17:00:00.000+00:00",
        endTs="2026-07-20T17:00:01.000+00:00",
    )

    assert item.start_ts.endswith("+00:00")

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
                "durationMs": 1_500,
            }
        ]
    )

    item = trace[0]
    assert isinstance(item, OperatorActionTraceItem)
    assert item.start_ts == "2026-07-20T17:00:00.000Z"
    assert item.end_ts == "2026-07-20T17:00:01.500Z"
    assert item.duration_ms == 1_500


@pytest.mark.parametrize(
    "timestamps",
    [
        {"startTs": "2026-07-20T17:00:00.000Z", "durationMs": 1_000},
        {"endTs": "2026-07-20T17:00:01.000Z", "durationMs": 1_000},
        {
            "startTs": "2026-07-20T17:00:02.000Z",
            "endTs": "2026-07-20T17:00:01.000Z",
            "durationMs": 0,
        },
        {
            "startTs": "not-a-timestamp",
            "endTs": "2026-07-20T17:00:01.000Z",
            "durationMs": 1_000,
        },
        {
            "startTs": "2026-07-20T17:00:00",
            "endTs": "2026-07-20T17:00:01",
            "durationMs": 1_000,
        },
        {"startTs": 1_000, "endTs": 2_000, "durationMs": 1_000},
        {
            "startTs": "2026-07-20T17:00:00.000Z",
            "endTs": "2026-07-20T17:00:01.000Z",
        },
        {
            "startTs": "2026-07-20T17:00:00.000Z",
            "endTs": "2026-07-20T17:00:01.000Z",
            "durationMs": 999,
        },
    ],
)
def test_operator_action_trace_rejects_invalid_timing(
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
        durationMs=1_000,
    )

    assert item.start_ts.endswith("+00:00")

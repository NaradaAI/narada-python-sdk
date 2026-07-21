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
                "startTs": 1_000,
                "endTs": 2_500,
            }
        ]
    )

    item = trace[0]
    assert isinstance(item, OperatorActionTraceItem)
    assert item.start_ts == 1_000
    assert item.end_ts == 2_500


@pytest.mark.parametrize(
    "timestamps",
    [
        {"startTs": 1_000},
        {"endTs": 2_000},
        {"startTs": 2_000, "endTs": 1_000},
    ],
)
def test_operator_action_trace_rejects_invalid_timestamp_ranges(
    timestamps: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        OperatorActionTraceItem(
            url="https://example.com",
            action="Clicked Submit",
            **timestamps,
        )

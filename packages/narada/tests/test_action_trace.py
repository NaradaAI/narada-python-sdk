from __future__ import annotations

import pytest
from narada_core.tracing.model import parse_action_trace
from pydantic import ValidationError


def test_operator_action_trace_uses_pythonic_timing_attributes_and_wire_aliases() -> (
    None
):
    trace = parse_action_trace(
        [
            {
                "url": "https://example.com/form",
                "action": "Clicked Save",
                "startTs": 1_000,
                "endTs": 1_240,
                "durationMs": 240,
                "children": [
                    {
                        "url": "https://example.com/form",
                        "action": "Validated Save",
                        "startTs": 1_050,
                        "endTs": 1_150,
                        "durationMs": 100,
                    }
                ],
            }
        ]
    )

    item = trace[0]
    assert item.start_ts == 1_000
    assert item.end_ts == 1_240
    assert item.duration_ms == 240
    assert item.children is not None
    assert item.children[0].duration_ms == 100
    assert item.model_dump(by_alias=True, exclude_none=True)["startTs"] == 1_000


@pytest.mark.parametrize(
    "timing",
    [
        {"startTs": 1_240, "endTs": 1_000, "durationMs": 0},
        {"startTs": 1_000, "endTs": 1_240, "durationMs": 0},
    ],
)
def test_operator_action_trace_rejects_inconsistent_timing(
    timing: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        parse_action_trace(
            [
                {
                    "url": "https://example.com/form",
                    "action": "Clicked Save",
                    **timing,
                }
            ]
        )


@pytest.mark.parametrize(
    "timing",
    [
        {},
        {"endTs": 1_240, "durationMs": 240},
        {"startTs": 1_000, "durationMs": 240},
        {"startTs": 1_000, "endTs": 1_240},
        {"startTs": None, "endTs": 1_240, "durationMs": 240},
    ],
)
def test_operator_action_trace_requires_complete_timing(
    timing: dict[str, int | None],
) -> None:
    with pytest.raises(ValidationError):
        parse_action_trace(
            [
                {
                    "url": "https://example.com/form",
                    "action": "Clicked Save",
                    **timing,
                }
            ]
        )


def test_operator_action_trace_requires_timing_on_nested_items() -> None:
    with pytest.raises(ValidationError):
        parse_action_trace(
            [
                {
                    "url": "https://example.com/form",
                    "action": "Clicked Save",
                    "startTs": 1_000,
                    "endTs": 1_240,
                    "durationMs": 240,
                    "children": [
                        {
                            "url": "https://example.com/form",
                            "action": "Validated Save",
                        }
                    ],
                }
            ]
        )


def test_operator_action_trace_accepts_timed_multiple_actions_and_done_event() -> None:
    trace = parse_action_trace(
        [
            {
                "url": "https://example.com/form",
                "action": "Multi-action",
                "startTs": 1_000,
                "endTs": 1_240,
                "durationMs": 240,
                "children": [
                    {
                        "url": "https://example.com/form",
                        "action": "Clicked Save",
                        "startTs": 1_010,
                        "endTs": 1_100,
                        "durationMs": 90,
                    },
                    {
                        "url": "https://example.com/form",
                        "action": "Typed a name",
                        "startTs": 1_100,
                        "endTs": 1_220,
                        "durationMs": 120,
                    },
                ],
            },
            {
                "url": "https://example.com/form",
                "action": "Done: saved",
                "startTs": 1_250,
                "endTs": 1_250,
                "durationMs": 0,
            },
        ]
    )

    assert trace[0].children is not None
    assert trace[0].children[1].duration_ms == 120
    assert trace[1].duration_ms == 0

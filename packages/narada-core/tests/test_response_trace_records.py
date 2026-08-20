import logging

from narada_core.tracing import AgentSpanData, Span, Trace, parse_response_trace


def test_parse_response_trace_preserves_valid_records_and_skips_invalid(
    caplog,
) -> None:
    records = parse_response_trace(
        [
            {
                "object": "trace",
                "trace_id": "trace_123",
                "name": "Operator",
                "group_id": None,
                "metadata": None,
            },
            {"object": "trace.span", "span_id": "missing-required-fields"},
            {
                "object": "trace.span",
                "span_id": "span_123",
                "trace_id": "trace_123",
                "parent_id": None,
                "started_at": "2026-07-29T12:00:00.000Z",
                "ended_at": "2026-07-29T12:00:01.000Z",
                "span_data": {
                    "type": "agent",
                    "name": "Operator",
                    "agent_type": "operator",
                    "prompt": "Find the Narada homepage",
                    "response": "Done",
                    "status": "success",
                    "request_id": "request_123",
                },
                "error": None,
            },
        ]
    )

    assert isinstance(records[0], Trace)
    assert isinstance(records[1], Span)
    assert isinstance(records[1].span_data, AgentSpanData)
    assert "index 1" in caplog.text


def test_parse_response_trace_is_best_effort_for_non_list_payload(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        records = parse_response_trace({"object": "trace"})

    assert records == []
    assert "not a list" in caplog.text

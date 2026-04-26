"""Tests for the private ``narada._trace`` module.

Covers the pure helpers (truncation, request/response summarisation) plus the
``emit_*`` functions, asserting that the JSON payloads emitted to the JS
harness match the ``PythonTraceEvent`` Pydantic schema defined in
``narada_core.actions.models``.
"""

from __future__ import annotations

import pytest
from narada_core.actions.models import (
    AgenticMouseActionRequest,
    AgenticSelectorRequest,
    CloseWindowRequest,
    GetFullHtmlRequest,
    GetFullHtmlResponse,
    GetScreenshotRequest,
    GetScreenshotResponse,
    GetSimplifiedHtmlRequest,
    GetSimplifiedHtmlResponse,
    GetUrlRequest,
    GetUrlResponse,
    GoToUrlRequest,
    PrintMessageRequest,
    PythonAgentRunTrace,
    ReadGoogleSheetRequest,
    ReadGoogleSheetResponse,
    WriteGoogleSheetRequest,
    parse_action_trace,
)

from narada import _trace


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_returns_none_for_none(self) -> None:
        assert _trace.truncate(None, 10) is None

    def test_preserves_short_strings(self) -> None:
        assert _trace.truncate("hello", 10) == "hello"

    def test_preserves_exact_length(self) -> None:
        assert _trace.truncate("1234567890", 10) == "1234567890"

    def test_truncates_long_strings_with_ellipsis(self) -> None:
        result = _trace.truncate("abcdefghij", 5)
        assert result is not None
        assert len(result) == 5
        assert result.endswith("\u2026")
        assert result.startswith("abcd")

    def test_truncate_prompt_falls_back_to_empty(self) -> None:
        assert _trace.truncate_prompt("") == ""

    def test_truncate_error_bounded(self) -> None:
        long = "x" * 5000
        result = _trace.truncate_error(long)
        assert len(result) == 1000
        assert result.endswith("\u2026")


# ---------------------------------------------------------------------------
# summarize_request / summarize_response
# ---------------------------------------------------------------------------


class TestSummarizeRequest:
    def test_go_to_url(self) -> None:
        req = GoToUrlRequest(url="https://example.com", new_tab=True)
        assert _trace.summarize_request(req) == {
            "url": "https://example.com",
            "new_tab": True,
        }

    @pytest.mark.parametrize(
        "request_instance",
        [
            GetUrlRequest(),
            GetScreenshotRequest(),
            GetFullHtmlRequest(),
            GetSimplifiedHtmlRequest(),
            CloseWindowRequest(),
        ],
    )
    def test_parameterless_requests_return_empty(
        self, request_instance: object
    ) -> None:
        assert _trace.summarize_request(request_instance) == {}  # type: ignore[arg-type]

    def test_read_google_sheet(self) -> None:
        req = ReadGoogleSheetRequest(spreadsheet_id="abc123", range="Sheet1!A1:B10")
        assert _trace.summarize_request(req) == {
            "spreadsheet_id": "abc123",
            "range": "Sheet1!A1:B10",
        }

    def test_write_google_sheet_reports_row_count_not_values(self) -> None:
        big_values = [["r"] * 5 for _ in range(847)]
        req = WriteGoogleSheetRequest(
            spreadsheet_id="abc123", range="Sheet1!A1:E847", values=big_values
        )
        summary = _trace.summarize_request(req)
        assert summary == {
            "spreadsheet_id": "abc123",
            "range": "Sheet1!A1:E847",
            "row_count": 847,
        }
        # Explicitly guard against regressions that leak row payloads.
        assert "values" not in summary

    def test_print_message_truncates_long_messages(self) -> None:
        long_msg = "x" * 2000
        summary = _trace.summarize_request(PrintMessageRequest(message=long_msg))
        truncated = summary["message"]
        assert isinstance(truncated, str)
        assert len(truncated) == 500
        assert truncated.endswith("\u2026")

    def test_agentic_selector_reports_action_type_and_truncates_query(self) -> None:
        req = AgenticSelectorRequest(
            action={"type": "click"},
            selectors={"id": "submit-btn"},
            fallback_operator_query="y" * 1000,
        )
        summary = _trace.summarize_request(req)
        assert summary["action_type"] == "click"
        assert len(summary["fallback_operator_query"]) == 200
        # Selectors are intentionally omitted (not user-useful in trace view).
        assert "selectors" not in summary

    def test_agentic_mouse_action(self) -> None:
        req = AgenticMouseActionRequest(
            action={"type": "click"},
            recorded_click={"x": 1, "y": 2, "viewport": {"width": 10, "height": 20}},
            fallback_operator_query="click the button",
            resize_window=False,
        )
        summary = _trace.summarize_request(req)
        assert summary == {
            "action_type": "click",
            "fallback_operator_query": "click the button",
        }


class TestSummarizeResponse:
    def test_get_url_returns_url(self) -> None:
        req = GetUrlRequest()
        resp = GetUrlResponse(url="https://example.com/page")
        assert _trace.summarize_response(req, resp) == {
            "url": "https://example.com/page"
        }

    def test_get_screenshot_returns_fixed_description(self) -> None:
        req = GetScreenshotRequest()
        resp = GetScreenshotResponse(
            base64_content="...huge blob...",
            name="page.png",
            mime_type="image/png",
            timestamp="2025-01-01T00:00:00Z",
        )
        summary = _trace.summarize_response(req, resp)
        assert summary == {"description": "Took screenshot of the page"}

    def test_full_html_returns_fixed_description(self) -> None:
        summary = _trace.summarize_response(
            GetFullHtmlRequest(), GetFullHtmlResponse(html="<html>...massive...</html>")
        )
        assert summary == {"description": "Got the full HTML of the page"}

    def test_simplified_html_returns_fixed_description(self) -> None:
        summary = _trace.summarize_response(
            GetSimplifiedHtmlRequest(),
            GetSimplifiedHtmlResponse(html="<html>short</html>"),
        )
        assert summary == {"description": "Got the simplified HTML of the page"}

    def test_read_google_sheet_reports_dimensions(self) -> None:
        req = ReadGoogleSheetRequest(spreadsheet_id="x", range="A1:C5")
        resp = ReadGoogleSheetResponse(values=[["a", "b", "c"], ["d", "e", "f"], ["g"]])
        assert _trace.summarize_response(req, resp) == {
            "row_count": 3,
            "column_count": 3,
        }

    def test_read_google_sheet_empty_values(self) -> None:
        req = ReadGoogleSheetRequest(spreadsheet_id="x", range="A1:C5")
        resp = ReadGoogleSheetResponse(values=[])
        assert _trace.summarize_response(req, resp) == {
            "row_count": 0,
            "column_count": 0,
        }

    def test_write_google_sheet_returns_none(self) -> None:
        req = WriteGoogleSheetRequest(spreadsheet_id="x", range="A1", values=[["v"]])
        assert _trace.summarize_response(req, None) is None

    def test_close_window_returns_none(self) -> None:
        assert _trace.summarize_response(CloseWindowRequest(), None) is None


# ---------------------------------------------------------------------------
# Event emitters
# ---------------------------------------------------------------------------


class TestEmitSubAgentCall:
    def test_success_with_action_trace(self, recorded_events) -> None:
        _trace.emit_sub_agent_call(
            ts_start=1000,
            agent_type="operator",
            prompt="Find leads",
            status="success",
            request_id="req_abc",
            action_trace_raw=[{"url": "https://sf.com", "action": "click Leads"}],
        )
        (event,) = recorded_events.events
        assert event["kind"] == "subAgentCall"
        assert event["ts_start"] == 1000
        assert event["ts_end"] >= 1000
        assert event["agent_type"] == "operator"
        assert event["prompt"] == "Find leads"
        assert event["status"] == "success"
        assert event["request_id"] == "req_abc"
        assert event["action_trace"] == [
            {"url": "https://sf.com", "action": "click Leads"}
        ]
        assert "error_message" not in event

    def test_success_without_action_trace_omits_field(self, recorded_events) -> None:
        _trace.emit_sub_agent_call(
            ts_start=1000, agent_type="operator", prompt="hi", status="success"
        )
        (event,) = recorded_events.events
        assert "action_trace" not in event
        assert "request_id" not in event

    def test_timeout_includes_error_message(self, recorded_events) -> None:
        _trace.emit_sub_agent_call(
            ts_start=1000,
            agent_type="operator",
            prompt="hi",
            status="timeout",
            error_message="Timed out after 60s",
        )
        (event,) = recorded_events.events
        assert event["status"] == "timeout"
        assert event["error_message"] == "Timed out after 60s"

    def test_error_truncates_error_message(self, recorded_events) -> None:
        _trace.emit_sub_agent_call(
            ts_start=1000,
            agent_type="operator",
            prompt="hi",
            status="error",
            error_message="x" * 5000,
        )
        (event,) = recorded_events.events
        assert len(event["error_message"]) == 1000

    def test_prompt_is_truncated(self, recorded_events) -> None:
        _trace.emit_sub_agent_call(
            ts_start=1000,
            agent_type="operator",
            prompt="y" * 1000,
            status="success",
        )
        (event,) = recorded_events.events
        assert len(event["prompt"]) == 500


class TestEmitExtensionAction:
    def test_success_with_result_summary(self, recorded_events) -> None:
        req = GetUrlRequest()
        resp = GetUrlResponse(url="https://x.com")
        _trace.emit_extension_action(
            ts_start=2000, request=req, status="success", response=resp
        )
        (event,) = recorded_events.events
        assert event["kind"] == "extensionAction"
        assert event["action_name"] == "get_url"
        assert event["request_summary"] == {}
        assert event["result_summary"] == {"url": "https://x.com"}
        assert event["status"] == "success"

    def test_success_without_result_summary_omits_field(self, recorded_events) -> None:
        req = WriteGoogleSheetRequest(
            spreadsheet_id="abc", range="A1:B2", values=[["1", "2"], ["3", "4"]]
        )
        _trace.emit_extension_action(ts_start=2000, request=req, status="success")
        (event,) = recorded_events.events
        assert event["request_summary"] == {
            "spreadsheet_id": "abc",
            "range": "A1:B2",
            "row_count": 2,
        }
        assert "result_summary" not in event

    def test_timeout(self, recorded_events) -> None:
        _trace.emit_extension_action(
            ts_start=0,
            request=GoToUrlRequest(url="https://a.b", new_tab=False),
            status="timeout",
            error_message="Timed out",
        )
        (event,) = recorded_events.events
        assert event["status"] == "timeout"
        assert event["action_name"] == "go_to_url"

    def test_error(self, recorded_events) -> None:
        _trace.emit_extension_action(
            ts_start=0,
            request=CloseWindowRequest(),
            status="error",
            error_message="permission denied",
        )
        (event,) = recorded_events.events
        assert event["status"] == "error"
        assert event["error_message"] == "permission denied"


class TestEmitSideEffect:
    def test_download_file(self, recorded_events) -> None:
        _trace.emit_side_effect(
            effect_type="download_file", description="Downloaded file: report.pdf"
        )
        (event,) = recorded_events.events
        assert event["kind"] == "sideEffect"
        assert event["effect_type"] == "download_file"
        assert event["description"] == "Downloaded file: report.pdf"
        assert "ts" in event

    def test_render_html(self, recorded_events) -> None:
        _trace.emit_side_effect(
            effect_type="render_html", description="Rendered HTML in a new tab"
        )
        (event,) = recorded_events.events
        assert event["effect_type"] == "render_html"


# ---------------------------------------------------------------------------
# End-to-end schema validation: every event kind produced by the emitters
# round-trips cleanly through the ``PythonAgentRunTrace`` Pydantic model and
# the ``parse_action_trace`` entry point used by downstream consumers.
# ---------------------------------------------------------------------------


class TestPythonAgentRunTraceRoundtrip:
    def test_every_event_kind_parses(self, recorded_events) -> None:
        _trace.emit_sub_agent_call(
            ts_start=1000,
            agent_type="operator",
            prompt="Find leads",
            status="success",
            request_id="req_abc",
            action_trace_raw=[{"url": "https://sf.com", "action": "click Leads"}],
        )
        _trace.emit_extension_action(
            ts_start=2000,
            request=GetScreenshotRequest(),
            status="success",
            response=GetScreenshotResponse(
                base64_content="ignored",
                name="page.png",
                mime_type="image/png",
                timestamp="now",
            ),
        )
        _trace.emit_side_effect(
            effect_type="download_file", description="Downloaded file: leads.csv"
        )

        # Assemble a representative PythonAgentRunTrace containing the emitted
        # events alongside stdout / stderr events (which are synthesised by
        # the JS-side runnable, not the SDK).
        stdout_stderr_events = [
            {"kind": "stdout", "ts": 500, "text": "starting"},
            {"kind": "stderr", "ts": 2500, "text": "deprecation warning"},
        ]
        events = stdout_stderr_events + recorded_events.events
        events.sort(key=lambda e: e.get("ts", e.get("ts_start", 0)))

        raw = [
            {
                "step_type": "pythonAgentRun",
                "url": "https://app.narada.ai/agent",
                "status": "success",
                "duration_ms": 3000,
                "events": events,
            }
        ]
        trace = parse_action_trace(raw)
        assert len(trace) == 1
        (node,) = trace
        assert isinstance(node, PythonAgentRunTrace)
        # Order reflects the real wall-clock timestamps: the emitters stamp
        # events with ``now_ms()`` at emit time, which in this test runs much
        # later than the synthetic stdout/stderr timestamps below. The side
        # effect therefore sorts after ``stderr`` (ts=2500).
        assert [e.kind for e in node.events] == [
            "stdout",
            "subAgentCall",
            "extensionAction",
            "stderr",
            "sideEffect",
        ]
        # Nested action_trace rehydrates correctly as an OperatorActionTrace.
        sub_call = node.events[1]
        assert sub_call.kind == "subAgentCall"
        assert sub_call.action_trace is not None
        assert sub_call.action_trace[0].url == "https://sf.com"

    def test_error_status_parses(self) -> None:
        raw = [
            {
                "step_type": "pythonAgentRun",
                "url": "https://x",
                "status": "error",
                "duration_ms": 120,
                "error_message": "ZeroDivisionError",
                "events": [],
            }
        ]
        trace = parse_action_trace(raw)
        assert isinstance(trace[0], PythonAgentRunTrace)
        assert trace[0].status == "error"
        assert trace[0].error_message == "ZeroDivisionError"


# ---------------------------------------------------------------------------
# Defensive emit: observability must never break the user's agent run
# ---------------------------------------------------------------------------


class TestEmitDefensive:
    def test_non_serialisable_payload_is_stringified_not_raised(
        self, recorded_events
    ) -> None:
        """A stray datetime / set / custom object in a summary should not crash
        user code mid-run. ``default=str`` stringifies and the event still
        reaches the harness."""
        import datetime as _dt

        _trace.emit_trace_event(
            {
                "kind": "stdout",
                "ts": _dt.datetime(2026, 1, 1),  # non-serialisable in std json
                "text": "hello",
            }
        )
        # Event was recorded (ts got stringified by default=str).
        assert len(recorded_events.events) == 1
        assert isinstance(recorded_events.events[0]["ts"], str)

    def test_harness_raising_does_not_propagate(self, monkeypatch) -> None:
        """If the JS-injected emitter raises, we swallow and log rather than
        propagate — tracing failures must not break the agent run."""

        def _boom(_json: str) -> None:
            raise RuntimeError("bridge down")

        # `_narada_emit_trace_event` is injected by the JS harness at runtime
        # (TYPE_CHECKING stub only in source); set without `raising` so the
        # assignment succeeds even when the attribute isn't yet bound.
        monkeypatch.setattr(_trace, "_narada_emit_trace_event", _boom, raising=False)
        # Must not raise.
        _trace.emit_trace_event({"kind": "stdout", "ts": 1, "text": "hi"})


# ---------------------------------------------------------------------------
# Nested action_trace forwarding: SDK forwards events as-is; size enforcement
# is the frontend's responsibility (MAX_NESTED_ACTION_TRACE_BYTES in
# python.worker.ts and the workflow-run-detail consumer caps).
# ---------------------------------------------------------------------------


class TestNestedActionTraceForwarding:
    def test_forwards_nested_python_events_unchanged(self, recorded_events) -> None:
        raw = [
            {
                "step_type": "pythonAgentRun",
                "url": "",
                "status": "success",
                "duration_ms": 10,
                "events": [
                    {"kind": "stdout", "ts": 1, "text": "a"},
                    {"kind": "stdout", "ts": 2, "text": "b"},
                ],
            }
        ]
        _trace.emit_sub_agent_call(
            ts_start=1,
            agent_type="custom_python",
            prompt="nested",
            status="success",
            action_trace_raw=raw,
        )
        event = recorded_events.events[0]
        inner = event["action_trace"][0]
        # Events are forwarded as-is; the SDK no longer strips them.
        assert inner["events"] == raw[0]["events"]
        assert "truncated_event_count" not in inner


# ---------------------------------------------------------------------------
# Pydantic invariants on new event models
# ---------------------------------------------------------------------------


class TestPythonEventInvariants:
    def test_sub_agent_call_rejects_ts_end_before_ts_start(self) -> None:
        from narada_core.actions.models import PythonSubAgentCallEvent
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="ts_end"):
            PythonSubAgentCallEvent(
                ts_start=1000,
                ts_end=999,
                agent_type="operator",
                prompt="p",
                status="success",
            )

    def test_extension_action_rejects_ts_end_before_ts_start(self) -> None:
        from narada_core.actions.models import PythonExtensionActionEvent
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="ts_end"):
            PythonExtensionActionEvent(
                ts_start=1000,
                ts_end=999,
                action_name="get_url",
                request_summary={},
                status="success",
            )

    def test_python_agent_run_rejects_negative_duration(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PythonAgentRunTrace(
                url="",
                status="success",
                duration_ms=-1,
                events=[],
            )


# ---------------------------------------------------------------------------
# Deterministic parse_action_trace selection
# ---------------------------------------------------------------------------


class TestParseActionTraceDispatch:
    def test_empty_list_parses_as_apa(self) -> None:
        result = parse_action_trace([])
        assert result == []

    def test_step_type_routes_to_apa_adapter(self) -> None:
        result = parse_action_trace(
            [{"step_type": "goToUrl", "url": "https://x", "description": "..."}]
        )
        assert result[0].step_type == "goToUrl"

    def test_action_plus_url_routes_to_operator_adapter(self) -> None:
        from narada_core.actions.models import OperatorActionTraceItem

        result = parse_action_trace([{"url": "https://x", "action": "click Foo"}])
        assert isinstance(result[0], OperatorActionTraceItem)
        assert result[0].action == "click Foo"

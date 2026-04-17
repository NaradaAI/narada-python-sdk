"""Private trace-emission helpers for narada-pyodide.

This module is used internally by narada-pyodide to forward structured
telemetry (sub-agent invocations, extension actions, side effects) from
Python code running inside the Pyodide worker to the JavaScript harness,
which assembles a ``PythonAgentRunTrace`` that surfaces on the Narada
observability dashboard.

The module is private: user code should not import from here. The public
surface lives in ``window.py`` and ``utils.py``; instrumentation is applied
at those module boundaries by calling into this module.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from narada_core.actions.models import (
    AgenticMouseActionRequest,
    AgenticSelectorRequest,
    CloseWindowRequest,
    ExtensionActionRequest,
    GetFullHtmlRequest,
    GetScreenshotRequest,
    GetSimplifiedHtmlRequest,
    GetUrlRequest,
    GetUrlResponse,
    GoToUrlRequest,
    PrintMessageRequest,
    ReadGoogleSheetRequest,
    ReadGoogleSheetResponse,
    WriteGoogleSheetRequest,
)
from pydantic import BaseModel

if TYPE_CHECKING:
    # Injected by the JavaScript harness at worker startup (see
    # `frontend/src/lib/apa/python/python.worker.ts`). narada-pyodide is
    # only ever imported under a Pyodide worker that has registered this
    # builtin; there is no non-Pyodide code path.
    def _narada_emit_trace_event(event_json: str) -> None: ...


# Hard caps on payload sizes carried in trace events. Values are large enough
# that typical prompts and error messages survive intact but small enough to
# bound worst-case persisted actionTrace JSON.
_MAX_PROMPT_CHARS = 500
_MAX_MESSAGE_CHARS = 500
_MAX_ERROR_CHARS = 1000
_MAX_QUERY_CHARS = 200

# When a sub-agent's response includes its own action trace (for example, the
# operator's step-by-step actions), we forward that trace one level deep so
# the dashboard can expand it. We do not forward deeper nesting — Python
# agents that delegate into other Python agents would otherwise produce
# exponentially-sized persisted traces.
_MAX_NESTED_ACTION_TRACE_DEPTH = 1

_ELLIPSIS = "\u2026"

_logger = logging.getLogger(__name__)


def now_ms() -> int:
    """Current wall-clock time in integer milliseconds."""
    return int(time.time() * 1000)


def truncate(value: str | None, max_chars: int) -> str | None:
    """Return ``value`` shortened to at most ``max_chars`` characters, suffixed
    with an ellipsis when truncation occurred. Returns ``None`` unchanged."""
    if value is None:
        return None
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + _ELLIPSIS


def truncate_prompt(prompt: str) -> str:
    return truncate(prompt, _MAX_PROMPT_CHARS) or ""


def truncate_error(error: str) -> str:
    return truncate(error, _MAX_ERROR_CHARS) or ""


def emit_trace_event(event: dict[str, Any]) -> None:
    """Forward a single trace event to the JavaScript harness.

    The event must be JSON-serialisable and shaped as one of the
    ``PythonTraceEvent`` variants defined in ``narada_core.actions.models``.
    No validation is performed here; callers construct events directly and
    are responsible for matching the schema.

    Observability must not break the thing it observes: any failure
    serialising or forwarding the event is logged and swallowed rather than
    propagated to user code. ``default=str`` catches stray non-serialisable
    values (timestamps, Pydantic models, numpy scalars) by stringifying them.
    """
    try:
        _narada_emit_trace_event(json.dumps(event, default=str))  # noqa: F821
    except Exception:  # noqa: BLE001 — broad by design; see docstring
        _logger.warning("trace event emission failed", exc_info=True)


def _strip_nested_python_events(
    raw: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Forward a nested action trace one level deep. Any ``pythonAgentRun``
    node inside retains its outer status/duration metadata but its ``events``
    list is dropped, preventing deep recursion from blowing up persisted
    JSON size. A ``truncated_event_count`` field is left behind so the
    dashboard can show that events were elided.
    """
    if raw is None:
        return None

    def strip(item: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(item, dict):
            return item
        if item.get("step_type") != "pythonAgentRun":
            return item
        events = item.get("events", [])
        stripped = dict(item)
        stripped["events"] = []
        stripped["truncated_event_count"] = (
            len(events) if isinstance(events, list) else 0
        )
        return stripped

    return [strip(item) for item in raw]


def summarize_request(request: ExtensionActionRequest) -> dict[str, Any]:
    """Produce a bounded-size summary of an extension action request for
    display in the observability dashboard. Large payloads (sheet row values,
    selector graphs) are reduced to row counts or action types; free-form
    strings are truncated.

    The returned dict is always JSON-serialisable and fits the
    ``PythonExtensionActionEvent.request_summary`` field.
    """
    if isinstance(request, GoToUrlRequest):
        return {"url": request.url, "new_tab": request.new_tab}
    if isinstance(
        request,
        (
            GetUrlRequest,
            GetScreenshotRequest,
            GetFullHtmlRequest,
            GetSimplifiedHtmlRequest,
            CloseWindowRequest,
        ),
    ):
        return {}
    if isinstance(request, ReadGoogleSheetRequest):
        return {"spreadsheet_id": request.spreadsheet_id, "range": request.range}
    if isinstance(request, WriteGoogleSheetRequest):
        return {
            "spreadsheet_id": request.spreadsheet_id,
            "range": request.range,
            "row_count": len(request.values),
        }
    if isinstance(request, PrintMessageRequest):
        return {"message": truncate(request.message, _MAX_MESSAGE_CHARS)}
    if isinstance(request, (AgenticSelectorRequest, AgenticMouseActionRequest)):
        return {
            "action_type": request.action["type"],
            "fallback_operator_query": truncate(
                request.fallback_operator_query, _MAX_QUERY_CHARS
            ),
        }
    # ExtensionActionRequest is a closed union today. If a new variant is
    # added without updating this function, we degrade gracefully to an empty
    # summary rather than crashing the user's agent mid-run.
    return {}


def summarize_response(
    request: ExtensionActionRequest,
    response: BaseModel | None,
) -> dict[str, Any] | None:
    """Produce a bounded-size summary of an extension action response, keyed
    on the originating request type. Returns ``None`` for actions that have
    no observable result (writes, navigations, close) so the dashboard can
    omit an empty row rather than rendering a hollow card.
    """
    if isinstance(request, GetUrlRequest) and isinstance(response, GetUrlResponse):
        return {"url": response.url}
    if isinstance(request, GetScreenshotRequest):
        return {"description": "Took screenshot of the page"}
    if isinstance(request, GetFullHtmlRequest):
        return {"description": "Got the full HTML of the page"}
    if isinstance(request, GetSimplifiedHtmlRequest):
        return {"description": "Got the simplified HTML of the page"}
    if isinstance(request, ReadGoogleSheetRequest) and isinstance(
        response, ReadGoogleSheetResponse
    ):
        rows = response.values
        column_count = max((len(row) for row in rows), default=0)
        return {"row_count": len(rows), "column_count": column_count}
    return None


# ---------------------------------------------------------------------------
# Event emitters
#
# Each emitter builds a JSON-serialisable event shaped to match one of the
# ``PythonTraceEvent`` Pydantic variants in ``narada_core.actions.models``
# and forwards it to the JavaScript harness. Optional fields are included
# only when non-None so the JSON stays compact.
# ---------------------------------------------------------------------------


SubAgentCallStatus = Literal["success", "error", "timeout"]
ExtensionActionStatus = Literal["success", "error", "timeout"]
SideEffectType = Literal["download_file", "render_html"]


def emit_sub_agent_call(
    *,
    ts_start: int,
    agent_type: str,
    prompt: str,
    status: SubAgentCallStatus,
    request_id: str | None = None,
    error_message: str | None = None,
    action_trace_raw: list[dict[str, Any]] | None = None,
) -> None:
    event: dict[str, Any] = {
        "kind": "subAgentCall",
        "ts_start": ts_start,
        "ts_end": now_ms(),
        "agent_type": agent_type,
        "prompt": truncate_prompt(prompt),
        "status": status,
    }
    if request_id is not None:
        event["request_id"] = request_id
    if error_message is not None:
        event["error_message"] = truncate_error(error_message)
    if action_trace_raw is not None:
        event["action_trace"] = _strip_nested_python_events(action_trace_raw)
    emit_trace_event(event)


def emit_extension_action(
    *,
    ts_start: int,
    request: ExtensionActionRequest,
    status: ExtensionActionStatus,
    response: BaseModel | None = None,
    error_message: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "kind": "extensionAction",
        "ts_start": ts_start,
        "ts_end": now_ms(),
        "action_name": request.name,
        "request_summary": summarize_request(request),
        "status": status,
    }
    result_summary = summarize_response(request, response)
    if result_summary is not None:
        event["result_summary"] = result_summary
    if error_message is not None:
        event["error_message"] = truncate_error(error_message)
    emit_trace_event(event)


def emit_side_effect(*, effect_type: SideEffectType, description: str) -> None:
    emit_trace_event(
        {
            "kind": "sideEffect",
            "ts": now_ms(),
            "effect_type": effect_type,
            "description": description,
        }
    )

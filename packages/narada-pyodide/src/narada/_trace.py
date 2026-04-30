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

from narada_core.actions.models import ExtensionActionRequest
from pydantic import BaseModel

if TYPE_CHECKING:
    # Injected by the JavaScript harness at worker startup. narada-pyodide is
    # only ever imported under a Pyodide worker that has registered this
    # builtin; there is no non-Pyodide code path.
    def _narada_emit_trace_event(event_json: str) -> None: ...


_logger = logging.getLogger(__name__)


def now_ms() -> int:
    """Current wall-clock time in integer milliseconds."""
    return int(time.time() * 1000)


def emit_trace_event(event: dict[str, Any]) -> None:
    """Forward a single trace event to the JavaScript harness.

    The event must be JSON-serialisable and shaped as one of the
    ``PythonTraceEvent`` variants defined in ``narada_core.tracing.model``.
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


def dump_model(model: BaseModel) -> dict[str, Any]:
    """Return the model's JSON-ready representation for trace persistence."""
    try:
        return model.model_dump(mode="json")
    except TypeError:
        # Some narada-core request models override model_dump without accepting
        # Pydantic's keyword arguments.
        return model.model_dump()


# ---------------------------------------------------------------------------
# Event emitters
#
# Each emitter builds a JSON-serialisable event shaped to match one of the
# ``PythonTraceEvent`` Pydantic variants in ``narada_core.tracing.model``
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
        "prompt": prompt,
        "status": status,
    }
    if request_id is not None:
        event["request_id"] = request_id
    if error_message is not None:
        event["error_message"] = error_message
    if action_trace_raw is not None:
        event["action_trace"] = action_trace_raw
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
        "request_summary": dump_model(request),
        "status": status,
    }
    if response is not None:
        event["result_summary"] = dump_model(response)
    if error_message is not None:
        event["error_message"] = error_message
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

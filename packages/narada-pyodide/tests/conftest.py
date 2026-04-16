"""Pytest fixtures shared across narada-pyodide tests.

narada-pyodide is designed to run inside a Pyodide web worker; several of its
transitive imports (``js``, ``pyodide.ffi``, ``pyodide.http``) are only
available in that environment. To make the pure-Python unit tests runnable on
a host CPython interpreter we stub those modules before any narada-pyodide
code is imported. The real Pyodide runtime will obviously provide them.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

# Stub Pyodide-only modules. Must happen before `from narada import _trace`.
for _mod in ("js", "pyodide", "pyodide.ffi", "pyodide.http"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest  # noqa: E402

from narada import _trace  # noqa: E402


class RecordingEmitter:
    """Captures every event forwarded by ``_trace.emit_trace_event`` during a
    test so assertions can inspect the JSON that would reach the JS harness.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, event_json: str) -> None:
        # Round-trip through json to catch non-serialisable payloads early.
        self.events.append(json.loads(event_json))


@pytest.fixture
def recorded_events() -> Iterator[RecordingEmitter]:
    """Replace the JS-harness-injected ``_narada_emit_trace_event`` with a
    recorder for the duration of a test, restoring the original binding
    afterwards.
    """
    emitter = RecordingEmitter()
    previous = getattr(_trace, "_narada_emit_trace_event", None)
    _trace._narada_emit_trace_event = emitter  # type: ignore[attr-defined]
    try:
        yield emitter
    finally:
        if previous is None:
            delattr(_trace, "_narada_emit_trace_event")
        else:
            _trace._narada_emit_trace_event = previous  # type: ignore[attr-defined]

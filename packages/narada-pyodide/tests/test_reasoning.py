"""Tests for the `reasoning` parameter on the Core Agent.

These exercise the `narada-pyodide` window because it is the only package with
a runnable test harness today; the impl in the sibling `narada` package shares
the same request-body wiring and runtime check, so coverage here verifies the
behavior across both code paths.

We mirror `test_cloud_browser.py`'s module-clearing pattern: each test gets a
fresh import of `narada.window` with a freshly stubbed `pyodide.http.pyfetch`,
because cached module references from earlier tests would otherwise leak into
this file when the suite runs in alphabetical order.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest


def _clear_modules() -> None:
    for name in list(sys.modules):
        if name == "narada" or name.startswith("narada."):
            sys.modules.pop(name, None)
    for name in ("js", "pyodide", "pyodide.http", "pyodide.ffi"):
        sys.modules.pop(name, None)


class _FakeResponse:
    def __init__(self, *, ok: bool = True, json_data: object = None) -> None:
        self.ok = ok
        self.status = 200
        self._json_data = json_data

    async def json(self) -> object:
        return self._json_data

    async def text(self) -> str:
        return ""


def _make_pyfetch_recorder() -> tuple[AsyncMock, list[dict[str, Any]]]:
    """Build an `AsyncMock` for `pyfetch` that captures every JSON body posted
    to /remote-dispatch and returns a canned success response on the poll."""
    posted_bodies: list[dict[str, Any]] = []

    async def _impl(url: str, **kwargs: Any) -> _FakeResponse:
        if "body" in kwargs:
            posted_bodies.append(json.loads(kwargs["body"]))
        if url.endswith("/remote-dispatch"):
            return _FakeResponse(json_data={"requestId": "req-test"})
        return _FakeResponse(
            json_data={
                "status": "success",
                "response": {
                    "text": "ok",
                    "output": {"type": "text", "content": "ok"},
                },
                "createdAt": "now",
                "completedAt": "now",
                "usage": {"actions": 0, "credits": 0.0},
            }
        )

    pyfetch = AsyncMock(side_effect=_impl)
    return pyfetch, posted_bodies


@pytest.fixture
def reimported_window(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[ModuleType, AsyncMock, list[dict[str, Any]]]]:
    """Force a fresh import of `narada.window` after planting freshly-mocked
    Pyodide-bridge modules. Yields the window module, the captured `pyfetch`
    mock, and the list that records every posted JSON body.
    """
    _clear_modules()

    js_module = ModuleType("js")
    js_module.AbortController = SimpleNamespace(  # type: ignore[attr-defined]
        new=lambda: SimpleNamespace(signal=object(), abort=lambda: None)
    )
    js_module.setTimeout = lambda callback, timeout: None  # type: ignore[attr-defined]

    pyodide_module = ModuleType("pyodide")
    pyodide_module.__path__ = []  # type: ignore[attr-defined]

    pyfetch, posted_bodies = _make_pyfetch_recorder()
    pyodide_http_module = ModuleType("pyodide.http")
    pyodide_http_module.pyfetch = pyfetch  # type: ignore[attr-defined]

    pyodide_ffi_module = ModuleType("pyodide.ffi")

    class _FakeJsProxy:
        def __init__(self, value: object) -> None:
            self._value = value

        def to_py(self) -> object:
            return self._value

    pyodide_ffi_module.JsProxy = _FakeJsProxy  # type: ignore[attr-defined]
    pyodide_ffi_module.create_once_callable = lambda fn: fn  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "js", js_module)
    monkeypatch.setitem(sys.modules, "pyodide", pyodide_module)
    monkeypatch.setitem(sys.modules, "pyodide.http", pyodide_http_module)
    monkeypatch.setitem(sys.modules, "pyodide.ffi", pyodide_ffi_module)

    window_module = importlib.import_module("narada.window")
    window_module._narada_parent_run_ids = _FakeJsProxy([])  # type: ignore[attr-defined]
    yield window_module, pyfetch, posted_bodies
    _clear_modules()


def _make_window(window_module: ModuleType) -> Any:
    window = window_module.LocalBrowserWindow.__new__(window_module.LocalBrowserWindow)
    window._auth_headers = {"x-narada-test": "1"}
    window._base_url = "https://example.invalid/api"
    window._browser_window_id = "test-window"

    async def _stub_auth_headers() -> dict[str, str]:
        return {"x-narada-test": "1"}

    window._get_auth_headers = _stub_auth_headers
    window._current_parent_run_ids = lambda: []
    return window


class TestReasoningBodyWiring:
    """The `reasoning` arg flows through to the JSON body as `reasoningMode`."""

    @pytest.mark.asyncio
    async def test_present_when_reasoning_is_set(
        self,
        reimported_window: tuple[ModuleType, AsyncMock, list[dict[str, Any]]],
    ) -> None:
        window_module, _pyfetch, posted_bodies = reimported_window
        from narada_core.models import Agent, ReasoningEffort

        window = _make_window(window_module)
        await window.dispatch_request(
            prompt="solve this",
            agent=Agent.CORE_AGENT,
            reasoning=ReasoningEffort.MEDIUM,
        )

        assert posted_bodies[0]["reasoningMode"] == "medium"

    @pytest.mark.asyncio
    async def test_absent_when_reasoning_is_none(
        self,
        reimported_window: tuple[ModuleType, AsyncMock, list[dict[str, Any]]],
    ) -> None:
        window_module, _pyfetch, posted_bodies = reimported_window
        from narada_core.models import Agent

        window = _make_window(window_module)
        await window.dispatch_request(
            prompt="solve this",
            agent=Agent.CORE_AGENT,
        )

        # Absent (not null) — wire-compatible with backends predating the field.
        assert "reasoningMode" not in posted_bodies[0]

    @pytest.mark.asyncio
    async def test_each_effort_level_serializes_to_string(
        self,
        reimported_window: tuple[ModuleType, AsyncMock, list[dict[str, Any]]],
    ) -> None:
        window_module, _pyfetch, posted_bodies = reimported_window
        from narada_core.models import Agent, ReasoningEffort

        window = _make_window(window_module)

        for level in (
            ReasoningEffort.NONE,
            ReasoningEffort.LOW,
            ReasoningEffort.MEDIUM,
            ReasoningEffort.HIGH,
        ):
            await window.dispatch_request(
                prompt="x",
                agent=Agent.CORE_AGENT,
                reasoning=level,
            )

        seen = [b["reasoningMode"] for b in posted_bodies if "reasoningMode" in b]
        assert seen == ["none", "low", "medium", "high"]


class TestReasoningRuntimeValidation:
    """Misuse — `reasoning` paired with a non-Core agent — fails fast at runtime
    with a clear message. The overload contract on the public `agent()` method
    catches this at type-check time when callers use the enum, but the runtime
    check covers the string-form (`agent="..."`) and untyped paths."""

    @pytest.mark.asyncio
    async def test_dispatch_request_rejects_non_core_agent_enum(
        self,
        reimported_window: tuple[ModuleType, AsyncMock, list[dict[str, Any]]],
    ) -> None:
        window_module, _pyfetch, _posted = reimported_window
        from narada_core.models import Agent, ReasoningEffort

        window = _make_window(window_module)
        with pytest.raises(ValueError, match="agent=Agent.CORE_AGENT"):
            await window.dispatch_request(
                prompt="x",
                agent=Agent.OPERATOR,
                reasoning=ReasoningEffort.MEDIUM,  # pyright: ignore[reportCallIssue]
            )

    @pytest.mark.asyncio
    async def test_dispatch_request_rejects_string_agent(
        self,
        reimported_window: tuple[ModuleType, AsyncMock, list[dict[str, Any]]],
    ) -> None:
        # String-form bypasses the type-checker overload, so the runtime check
        # is the only safety net here.
        window_module, _pyfetch, _posted = reimported_window
        from narada_core.models import ReasoningEffort

        window = _make_window(window_module)
        with pytest.raises(ValueError, match="agent=Agent.CORE_AGENT"):
            await window.dispatch_request(
                prompt="x",
                agent="some-custom-agent",
                reasoning=ReasoningEffort.HIGH,  # pyright: ignore[reportCallIssue]
            )

    @pytest.mark.asyncio
    async def test_agent_rejects_non_core_agent_enum(
        self,
        reimported_window: tuple[ModuleType, AsyncMock, list[dict[str, Any]]],
    ) -> None:
        # The same constraint must hold on the higher-level `agent()` method.
        window_module, _pyfetch, _posted = reimported_window
        from narada_core.models import Agent, ReasoningEffort

        window = _make_window(window_module)
        with pytest.raises(ValueError, match="agent=Agent.CORE_AGENT"):
            await window.agent(
                prompt="x",
                agent=Agent.OPERATOR,
                reasoning=ReasoningEffort.LOW,  # pyright: ignore[reportCallIssue]
            )


class TestReasoningEffortEnum:
    """The enum values are exactly what the backend expects."""

    def test_values_match_backend_literal(self) -> None:
        # The backend declares `reasoningMode: Literal["none", "low",
        # "medium", "high"] | None`. If we drift, requests will start failing
        # validation server-side.
        from narada_core.models import ReasoningEffort

        assert ReasoningEffort.NONE.value == "none"
        assert ReasoningEffort.LOW.value == "low"
        assert ReasoningEffort.MEDIUM.value == "medium"
        assert ReasoningEffort.HIGH.value == "high"

    def test_str_enum_serializes_inline(self) -> None:
        # `StrEnum` values double as `str`, which is what `json.dumps` writes
        # without any custom encoder.
        from narada_core.models import ReasoningEffort

        assert json.dumps({"reasoningMode": ReasoningEffort.MEDIUM.value}) == (
            '{"reasoningMode": "medium"}'
        )

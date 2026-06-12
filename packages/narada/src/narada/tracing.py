from __future__ import annotations

from contextvars import ContextVar, Token
from pathlib import Path
from types import TracebackType
from typing import Any

from narada_core.actions.models import AgentResponse

from narada.workbench import MaterializedTrace, materialize_execution_trace_context

_ACTIVE_TRACE_SESSION: ContextVar[TraceSession | None] = ContextVar(
    "narada_active_trace_session",
    default=None,
)


class TraceSession:
    def __init__(self, label: str, *, out: str | Path | None = None) -> None:
        self.label = label
        self.out = Path(out) if out is not None else None
        self.paths: list[Path] = []
        self.path: Path | None = None
        self._responses: list[tuple[AgentResponse[Any], dict[str, str], str]] = []
        self._token: Token[TraceSession | None] | None = None

    async def __aenter__(self) -> TraceSession:
        self._token = _ACTIVE_TRACE_SESSION.set(self)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc, tb
        try:
            try:
                await self.materialize()
            except Exception:
                if exc_type is None:
                    raise
        finally:
            if self._token is not None:
                _ACTIVE_TRACE_SESSION.reset(self._token)
                self._token = None

    def register_response(
        self,
        response: AgentResponse[Any],
        *,
        auth_headers: dict[str, str],
        base_url: str,
    ) -> None:
        if response.execution_trace_context is None:
            return
        self._responses.append((response, dict(auth_headers), base_url))

    async def materialize(self) -> list[MaterializedTrace]:
        results: list[MaterializedTrace] = []
        for index, (response, auth_headers, base_url) in enumerate(
            self._responses,
            start=1,
        ):
            if response.execution_trace_context is None:
                continue
            if self.out is None:
                out = None
            elif len(self._responses) == 1:
                out = self.out
            else:
                out = self.out / f"run-{index}-{response.request_id}"
            result = await materialize_execution_trace_context(
                response.execution_trace_context,
                out=out,
                label=f"{self.label}-{response.request_id}",
                source_run={
                    "type": "remote-dispatch",
                    "authority": "agent-run-response",
                    "requestId": response.request_id,
                    "status": response.status,
                },
                auth_headers=auth_headers,
                base_url=base_url,
            )
            response.execution_trace_path = str(result.path)
            results.append(result)
            self.paths.append(result.path)
        self.path = results[-1].path if results else None
        return results


def trace(label: str, *, out: str | Path | None = None) -> TraceSession:
    return TraceSession(label, out=out)


def get_active_trace_session() -> TraceSession | None:
    return _ACTIVE_TRACE_SESSION.get()

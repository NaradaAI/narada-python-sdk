"""In-process SDK evidence for an explicitly bound local workflow run.

The runner owns manifest/output/process lifecycle. The SDK owns request evidence;
it never edits the runner manifest or loads an ambient Python startup patch.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from narada.execution_traces import (
    ExecutionTraceClient,
    ExecutionTraceError,
    _validate_request_id,
)

logger = logging.getLogger(__name__)


class _ActiveRunManifest(BaseModel):
    model_config = ConfigDict(strict=True)

    schemaVersion: Literal[1]
    runId: str
    status: Literal["running"]


class _RequestEvidence(BaseModel):
    schemaVersion: Literal[1] = 1
    requestId: str
    role: Literal["primary", "critic"] = "primary"
    parentRequestId: str | None = None
    status: Literal["pending", "complete", "unavailable", "failed"] = "pending"
    traceId: str | None = None
    reason: str | None = None


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    # Write and replace in the same directory, so readers never see partial JSON.
    if path.is_symlink():
        raise ValueError("Evidence path must not be a symlink")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class RunEvidence:
    def __init__(self, run_dir: Path) -> None:
        self._requests_dir = run_dir / "artifacts" / "requests"
        if self._requests_dir.is_symlink():
            raise ValueError("Run request directory must not be a symlink")
        self._requests_dir.mkdir(exist_ok=True)

    @classmethod
    def from_environment(cls) -> RunEvidence | None:
        """Unset disables recording; malformed bindings fail before dispatch.

        Only NARADA_RUN_DIR is consumed. It names a runner-prepared directory,
        whose manifest must be active and whose 128-bit ID matches its basename.
        """
        raw = os.environ.get("NARADA_RUN_DIR")
        if raw is None:
            return None
        try:
            run_dir = Path(raw)
            if (
                not run_dir.is_absolute()
                or run_dir.is_symlink()
                or not run_dir.is_dir()
            ):
                raise ValueError
            if re.fullmatch(r"[0-9a-f]{32}", run_dir.name) is None:
                raise ValueError
            for filename in ("manifest.json", "output.log", "artifacts"):
                candidate = run_dir / filename
                if candidate.is_symlink():
                    raise ValueError
                if filename == "artifacts":
                    if not candidate.is_dir():
                        raise ValueError
                elif not candidate.is_file():
                    raise ValueError
            manifest_path = run_dir / "manifest.json"
            if manifest_path.stat().st_size > 64 * 1024:
                raise ValueError
            manifest = _ActiveRunManifest.model_validate_json(
                manifest_path.read_bytes()
            )
            if manifest.runId != run_dir.name:
                raise ValueError
            return cls(run_dir)
        except (OSError, ValueError, ValidationError):
            raise ValueError(
                "NARADA_RUN_DIR must name a valid active Narada run directory"
            ) from None

    def _directory(self, request_id: str) -> Path:
        _validate_request_id(request_id)
        directory = self._requests_dir / request_id
        if directory.is_symlink():
            raise ValueError("Request evidence directory must not be a symlink")
        directory.mkdir(exist_ok=True)
        return directory

    def admitted(self, request_id: str, *, parent_request_id: str | None) -> None:
        try:
            evidence = _RequestEvidence(
                requestId=request_id,
                parentRequestId=parent_request_id,
                role="critic" if parent_request_id is not None else "primary",
            )
            _write_json(
                self._directory(request_id) / "evidence.json", evidence.model_dump()
            )
        except Exception:
            logger.warning(
                "Narada request evidence could not be saved (local_evidence_failed)"
            )

    def interrupted(self, request_id: str, *, parent_request_id: str | None) -> None:
        try:
            evidence = _RequestEvidence(
                requestId=request_id,
                parentRequestId=parent_request_id,
                role="critic" if parent_request_id is not None else "primary",
                status="failed",
                reason="dispatch_not_completed",
            )
            _write_json(
                self._directory(request_id) / "evidence.json", evidence.model_dump()
            )
        except Exception:
            logger.warning(
                "Narada request evidence could not be saved (local_evidence_failed)"
            )

    async def completed(
        self,
        response: Mapping[str, Any],
        *,
        client: ExecutionTraceClient,
        parent_request_id: str | None,
    ) -> None:
        """Save the actual completed response before fetching optional evidence.

        The response is business data, intentionally readable by the user's agent.
        Requests, auth headers, signed archive locations and exception strings are
        not persisted. Evidence failure never changes the completed action result.
        """
        evidence: _RequestEvidence | None = None
        directory: Path | None = None
        try:
            request_id = response["requestId"]
            directory = self._directory(request_id)
            _write_json(directory / "response.json", response)
            content = response.get("response") or {}
            context = content.get("executionTraceContext") or {}
            evidence = _RequestEvidence(
                requestId=request_id,
                parentRequestId=parent_request_id,
                role="critic" if parent_request_id is not None else "primary",
                traceId=context.get("traceId"),
            )
            _write_json(directory / "evidence.json", evidence.model_dump())
            result = await client.fetch(
                request_id=request_id,
                destination=directory / "execution-trace",
                expected_trace_id=evidence.traceId,
            )
            evidence.status = result.status
            evidence.traceId = result.trace_id or evidence.traceId
            _write_json(directory / "evidence.json", evidence.model_dump())
        except Exception as error:
            reason = (
                error.reason
                if isinstance(error, ExecutionTraceError)
                else "local_evidence_failed"
            )
            if directory is not None and evidence is not None:
                try:
                    evidence.status = "failed"
                    evidence.reason = reason
                    _write_json(directory / "evidence.json", evidence.model_dump())
                except Exception:
                    pass
            logger.warning(
                "Narada action completed; execution evidence is incomplete (%s)", reason
            )

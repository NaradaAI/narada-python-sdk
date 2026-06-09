from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from narada_core.execution_trace import ExecutionTraceContext

from narada._workbench_contract import (
    BINARY_SCAN_SUFFIXES,
    CLEAN_COMMAND_STATUSES,
    REDACTION_REPORT_JSON,
    REDACTION_REPORT_MD,
    REQUIRED_PROOF_FILES,
)

DEFAULT_API_BASE_URL = "https://api.narada.ai/fast/v2"

_SIGNED_URL_PATTERNS = (
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "awsaccesskeyid",
)
_SECRET_PATTERNS = (
    re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE),
    re.compile(r'"authorization"\s*:\s*"Bearer\s+[^"]+"', re.IGNORECASE),
    re.compile(r"\bcookie\s*:\s*[^\n\r]+", re.IGNORECASE),
    re.compile(r'"cookie"\s*:\s*"[^"]+"', re.IGNORECASE),
    re.compile(r"x-api-key\s*[:=]\s*['\"]?[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"NARADA_API_KEY\s*=\s*['\"]?[^'\"\s,}]+", re.IGNORECASE),
    re.compile(
        r'"(?:plaintextKey|apiKey|accessToken|refreshToken|idToken|authToken|token)"\s*:\s*"[^"]+"',
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:plaintextKey|apiKey|accessToken|refreshToken|idToken|authToken|token)\s*[:=]\s*['\"]?[^'\"\s,}]+",
        re.IGNORECASE,
    ),
    re.compile(r"callbackSecret\s*[:=]\s*['\"]?[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"secretVariables\s*[:=]", re.IGNORECASE),
    re.compile(r"NARADA_TEST_SECRET_SHOULD_FAIL"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_SELF_REVIEW_PATTERNS = (
    re.compile(r"workflowSelfApproved", re.IGNORECASE),
    re.compile(r"manual_review_accepted_by_workflow", re.IGNORECASE),
    re.compile(r"self_review_accepted", re.IGNORECASE),
    re.compile(r"approvedBy[\"'\s:=]+workflow", re.IGNORECASE),
    re.compile(r"reviewStatus[\"'\s:=]+accepted", re.IGNORECASE),
    re.compile(r"manualReview[\"'\s:=]+pass", re.IGNORECASE),
)
_STATIC_ANSWER_PATTERNS = (
    re.compile(r"\bVALUE_RULES\b"),
    re.compile(r"\bSTATUS_FACTS\b"),
    re.compile(r"\bPRICE_FACTS\b"),
    re.compile(r"\bANSWER_MAP\b"),
    re.compile(r"source-facts\.json"),
    re.compile(r"source-inventory\.json"),
)
_FAILED_STATUSES = (
    "failed",
    "failure",
    "error",
    "errored",
    "aborted",
    "cancelled",
    "canceled",
    "timeout",
    "timed_out",
)
_SUCCESS_STATUSES = (
    "success",
    "succeeded",
    "completed",
    "complete",
    "passed",
)
_NON_TERMINAL_STATUSES = (
    "input-required",
    "input_required",
    "pending",
    "queued",
    "running",
    "in-progress",
    "in_progress",
)
_CLEAN_SOURCE_AUTHORITIES = (
    "remote-dispatch-response-api",
    "agent-run-response",
)


@dataclass(frozen=True)
class MaterializedTrace:
    path: Path
    manifest: dict[str, Any]
    report: dict[str, Any]


def default_auth_headers() -> dict[str, str]:
    api_key = os.getenv("NARADA_API_KEY")
    return {"x-api-key": api_key} if api_key else {}


def default_api_base_url() -> str:
    return os.getenv("NARADA_API_BASE_URL", DEFAULT_API_BASE_URL)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned[:80] or "trace"


def _default_out_dir(label: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(".narada") / "workbench-runs" / f"{timestamp}-{_safe_slug(label)}"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _redact_url(value: str) -> str:
    split = urlsplit(value)
    if not split.query:
        return value
    return urlunsplit((split.scheme, split.netloc, split.path, "", ""))


def _url_origin(value: str) -> str:
    split = urlsplit(value)
    return urlunsplit((split.scheme, split.netloc, "", "", ""))


def _redact_sensitive_text(value: str) -> str:
    redacted = value
    for marker in _SIGNED_URL_PATTERNS:
        redacted = re.sub(
            rf"(\S*{re.escape(marker)}\S*)",
            "[REDACTED_SIGNED_URL]",
            redacted,
            flags=re.IGNORECASE,
        )
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def _warning_codes(warnings: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(warning.get("code"))
            for warning in warnings
            if warning.get("code") not in {"command_warning"}
        }
    )


def _frame_dir(root: Path, frame: dict[str, Any], index: int) -> Path:
    frame_id = str(frame.get("frameId") or f"frame_{index}")
    return root / "trace" / "frames" / _safe_slug(frame_id)


def _frame_summary(frame: dict[str, Any]) -> dict[str, Any]:
    page = frame.get("page") if isinstance(frame.get("page"), dict) else {}
    return {
        "schemaVersion": 1,
        "frameId": frame.get("frameId"),
        "sequence": frame.get("sequence"),
        "capturedAt": frame.get("capturedAt"),
        "reason": frame.get("reason"),
        "page": {
            "url": page.get("url"),
            "title": page.get("title"),
        },
        "eventIds": frame.get("eventIds")
        if isinstance(frame.get("eventIds"), list)
        else [],
        "hasHtmlRef": bool(frame.get("htmlS3Key")),
        "hasScreenshotRef": bool(frame.get("screenshotS3Key")),
    }


def _is_failed_status(value: Any) -> bool:
    return isinstance(value, str) and value.lower() in _FAILED_STATUSES


def _is_unknown_status(value: Any) -> bool:
    return not isinstance(value, str) or not value or value.lower() == "unknown"


def _is_success_status(value: Any) -> bool:
    return isinstance(value, str) and value.lower() in _SUCCESS_STATUSES


def _is_non_terminal_status(value: Any) -> bool:
    return isinstance(value, str) and value.lower() in _NON_TERMINAL_STATUSES


def _is_clean_source_authority(value: Any) -> bool:
    return isinstance(value, str) and value in _CLEAN_SOURCE_AUTHORITIES


def _status_exit_code(status: str) -> int:
    return 0 if status in CLEAN_COMMAND_STATUSES or status == "passed" else 1


def _artifact_ref(root: Path, relative_path: str, role: str) -> dict[str, Any]:
    path = root / relative_path
    return {"path": relative_path, "role": role, "sha256": _sha256_file(path)}


def _source_run_problems(source_run: dict[str, Any]) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    taints: list[str] = []
    source_status = source_run.get("status")
    if _is_unknown_status(source_status):
        taints.append("source_run_status_unknown")
    elif _is_failed_status(source_status):
        failures.append("source_run_failed")
    elif _is_non_terminal_status(source_status):
        failures.append("source_run_not_terminal")
    elif not _is_success_status(source_status):
        taints.append("source_run_status_unrecognized")

    authority = source_run.get("authority")
    if not _is_clean_source_authority(authority):
        taints.append("source_run_authority_unverified")
    return failures, taints


def _collect_artifact_keys_from_artifacts(artifacts: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for name, value in artifacts.items():
        if name.endswith("S3Key") and isinstance(value, str) and value:
            keys.add(value)
        elif name.endswith("S3Keys") and isinstance(value, list):
            keys.update(item for item in value if isinstance(item, str) and item)
    return keys


def _collect_resolved_trace_artifact_keys(
    context: dict[str, Any],
    resolved_trace: dict[str, Any],
) -> set[str]:
    keys = {
        value
        for key in (
            "executionTraceS3Key",
            "executionTraceSegmentS3Key",
            "rootExecutionTraceS3Key",
        )
        if isinstance((value := context.get(key)), str) and value
    }
    manifest = resolved_trace.get("manifest")
    if isinstance(manifest, dict):
        artifacts = manifest.get("artifacts")
        if isinstance(artifacts, dict):
            keys.update(_collect_artifact_keys_from_artifacts(artifacts))
        for segment in manifest.get("segments") or []:
            if isinstance(segment, dict) and isinstance(segment.get("indexS3Key"), str):
                keys.add(segment["indexS3Key"])
    for segment_manifest in resolved_trace.get("segments") or []:
        if not isinstance(segment_manifest, dict):
            continue
        artifacts = segment_manifest.get("artifacts")
        if isinstance(artifacts, dict):
            keys.update(_collect_artifact_keys_from_artifacts(artifacts))
        for segment in segment_manifest.get("segments") or []:
            if isinstance(segment, dict) and isinstance(segment.get("indexS3Key"), str):
                keys.add(segment["indexS3Key"])
    for frame in resolved_trace.get("frames") or []:
        if not isinstance(frame, dict):
            continue
        for key in ("frameS3Key", "htmlS3Key", "screenshotS3Key"):
            value = frame.get(key)
            if isinstance(value, str) and value:
                keys.add(value)
    return keys


async def _fetch_json(
    url: str,
    *,
    method: str = "GET",
    auth_headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    session_factory: Callable[[], Any] = aiohttp.ClientSession,
) -> dict[str, Any]:
    async with session_factory() as session:
        request = session.post if method.upper() == "POST" else session.get
        kwargs: dict[str, Any] = {"headers": auth_headers or {}}
        if json_body is not None:
            kwargs["json"] = json_body
        async with request(url, **kwargs) as response:
            response.raise_for_status()
            payload = await response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from {url}")
    return payload


async def _download_bytes(
    url: str,
    *,
    session_factory: Callable[[], Any] = aiohttp.ClientSession,
) -> bytes:
    async with session_factory() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()


async def resolve_execution_trace(
    context: dict[str, Any],
    *,
    auth_headers: dict[str, str] | None = None,
    base_url: str | None = None,
    session_factory: Callable[[], Any] = aiohttp.ClientSession,
) -> dict[str, Any]:
    validated = ExecutionTraceContext.model_validate(context)
    return await _fetch_json(
        f"{base_url or default_api_base_url()}/execution-trace/resolve",
        method="POST",
        auth_headers=auth_headers
        if auth_headers is not None
        else default_auth_headers(),
        json_body={"executionTraceContext": validated.model_dump(mode="json")},
        session_factory=session_factory,
    )


async def materialize_execution_trace_context(
    context: dict[str, Any],
    *,
    out: str | Path | None = None,
    label: str | None = None,
    source_run: dict[str, Any] | None = None,
    auth_headers: dict[str, str] | None = None,
    base_url: str | None = None,
    session_factory: Callable[[], Any] = aiohttp.ClientSession,
) -> MaterializedTrace:
    validated = ExecutionTraceContext.model_validate(context)
    proof_root = (
        Path(out) if out is not None else _default_out_dir(label or validated.label)
    )
    preexisting_root = proof_root.exists() and any(proof_root.iterdir())
    proof_root.mkdir(parents=True, exist_ok=True)
    (proof_root / "cleanup").mkdir(parents=True, exist_ok=True)
    taints = ["proof_root_preexisting"] if preexisting_root else []
    failures: list[str] = []
    if source_run is None:
        source_run = {"type": "unknown", "status": "unknown"}
        taints.append("source_run_status_unknown")
        taints.append("source_run_authority_unverified")
    else:
        source_failures, source_taints = _source_run_problems(source_run)
        failures.extend(source_failures)
        taints.extend(source_taints)

    resolved_response = await resolve_execution_trace(
        validated.model_dump(mode="json"),
        auth_headers=auth_headers,
        base_url=base_url,
        session_factory=session_factory,
    )
    resolved_trace = resolved_response["resolvedTrace"]
    artifacts = resolved_response.get("artifacts") or []
    if not isinstance(artifacts, list):
        raise ValueError("execution-trace resolve response artifacts must be a list")

    trace_root = proof_root / "trace"
    _write_json(trace_root / "context.json", validated.model_dump(mode="json"))
    _write_json(trace_root / "resolved.json", resolved_trace)
    _write_jsonl(trace_root / "events.jsonl", resolved_trace.get("events") or [])
    _write_jsonl(trace_root / "scopes.jsonl", resolved_trace.get("scopes") or [])
    _write_json(
        trace_root / "timeline.json", resolved_trace.get("timeline_index") or {}
    )

    frames = resolved_trace.get("frames") or []
    if isinstance(frames, list):
        for index, frame in enumerate(frames, start=1):
            if isinstance(frame, dict):
                frame_root = _frame_dir(proof_root, frame, index)
                _write_json(frame_root / "frame.json", frame)
                _write_json(frame_root / "summary.json", _frame_summary(frame))

    artifact_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    role_counts: dict[str, int] = {}
    frames_by_id = {
        str(frame.get("frameId")): frame
        for frame in frames
        if isinstance(frame, dict) and frame.get("frameId")
    }

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            warnings.append("Skipping non-object artifact ref")
            continue
        role = str(artifact.get("role") or "artifact")
        source_key = str(artifact.get("s3Key") or "")
        download_url = str(artifact.get("downloadUrl") or "")
        if not source_key or not download_url:
            warnings.append(f"Skipping incomplete artifact ref for role {role}")
            continue
        role_counts[role] = role_counts.get(role, 0) + 1
        frame_id = artifact.get("frameId")
        frame = frames_by_id.get(str(frame_id)) if frame_id else None

        if role in {"html", "screenshot", "frame"} and isinstance(frame, dict):
            target_dir = _frame_dir(proof_root, frame, role_counts[role])
            filename = {
                "html": "page.html",
                "screenshot": "screenshot.png",
                "frame": "frame.json",
            }[role]
            local_path = target_dir / filename
        else:
            extension = {
                "manifest": ".json",
                "events": ".jsonl",
                "scopes": ".jsonl",
                "timeline": ".json",
                "html": ".html",
                "screenshot": ".png",
                "frame": ".json",
            }.get(role, ".bin")
            local_path = (
                trace_root / "artifacts" / f"{role}_{role_counts[role]}{extension}"
            )

        try:
            data = await _download_bytes(download_url, session_factory=session_factory)
        except Exception as exc:
            failures.append(f"artifact_download_failed:{source_key}")
            warnings.append(f"Failed to download artifact for role {role}")
            artifact_rows.append(
                {
                    "role": role,
                    "sourceS3Key": source_key,
                    "localPath": None,
                    "downloadStatus": "failed",
                    "errorType": type(exc).__name__,
                    "contentType": artifact.get("contentType"),
                    "sensitive": bool(artifact.get("sensitive", True)),
                    "frameId": artifact.get("frameId"),
                    "label": artifact.get("label"),
                    "redactedDownloadUrl": _redact_url(download_url),
                }
            )
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        artifact_rows.append(
            {
                "role": role,
                "sourceS3Key": source_key,
                "localPath": _relative(local_path, proof_root),
                "downloadStatus": "downloaded",
                "sha256": _sha256_bytes(data),
                "bytes": len(data),
                "contentType": artifact.get("contentType"),
                "sensitive": bool(artifact.get("sensitive", True)),
                "frameId": artifact.get("frameId"),
                "label": artifact.get("label"),
                "redactedDownloadUrl": _redact_url(download_url),
            }
        )

    artifact_index_path = trace_root / "artifacts" / "index.jsonl"
    _write_jsonl(artifact_index_path, artifact_rows)
    artifact_index_hash = _sha256_file(artifact_index_path)
    redaction_report = _write_redaction_report(proof_root)
    for finding in redaction_report["findings"]:
        if finding["severity"] == "failure":
            failures.append(f"redaction:{finding['code']}:{finding['path']}")
        elif finding["severity"] == "taint":
            taints.append(f"redaction:{finding['code']}:{finding['path']}")
    manifest = {
        "schemaVersion": 1,
        "runId": proof_root.name,
        "label": label or validated.label,
        "createdAt": _now_iso(),
        "apiBaseUrl": base_url or default_api_base_url(),
        "apiBaseUrlOrigin": _url_origin(base_url or default_api_base_url()),
        "status": "failed" if failures else ("tainted" if taints else "materialized"),
        "traceContext": validated.model_dump(mode="json"),
        "traceId": validated.traceId,
        "sourceRun": source_run,
        "traceContextHash": _sha256_json(validated.model_dump(mode="json")),
        "resolvedTraceHash": _sha256_json(resolved_trace),
        "artifactIndexHash": artifact_index_hash,
        "traceContextStatus": validated.status,
        "traceManifestStatus": (resolved_trace.get("manifest") or {}).get("status")
        if isinstance(resolved_trace.get("manifest"), dict)
        else None,
        "counts": {
            "events": len(resolved_trace.get("events") or []),
            "scopes": len(resolved_trace.get("scopes") or []),
            "frames": len(frames) if isinstance(frames, list) else 0,
            "artifacts": len(artifact_rows),
        },
        "sensitiveArtifacts": True,
        "taints": taints,
        "failures": failures,
    }
    _write_json(proof_root / "manifest.json", manifest)
    _write_json(
        proof_root / "cleanup" / "status.json",
        {
            "status": "not_applicable",
            "reason": "trace materialization opened no environment",
        },
    )
    report = {
        "schemaVersion": 1,
        "status": "failed"
        if failures
        else ("tainted" if taints else ("passed" if not warnings else "needs_review")),
        "proofRoot": str(proof_root),
        "warnings": warnings,
        "taints": taints,
        "failures": failures,
        "artifactCount": len(artifact_rows),
    }
    _write_json(proof_root / "reports" / "materialization-report.json", report)
    (proof_root / "reports" / "materialization-report.md").write_text(
        f"# Materialization Report\n\nStatus: {report['status']}\n\nArtifacts: {len(artifact_rows)}\n",
        encoding="utf-8",
    )
    append_command(
        proof_root,
        command="trace.materialize",
        status=report["status"],
        artifacts=[
            {"path": "trace/resolved.json", "role": "resolved-trace"},
            {"path": "trace/artifacts/index.jsonl", "role": "artifact-index"},
        ],
        warnings=warnings,
        taints=taints,
        ids={
            "traceId": validated.traceId,
            "contextHash": manifest["traceContextHash"],
            "resolvedTraceHash": manifest["resolvedTraceHash"],
            "artifactIndexHash": manifest["artifactIndexHash"],
            "sourceRunStatus": source_run.get("status"),
            "sourceRunAuthority": source_run.get("authority"),
        },
        inputs={
            "sourceType": "context",
            "apiBaseUrlOrigin": manifest["apiBaseUrlOrigin"],
        },
    )
    _update_manifest_hash(
        proof_root, "commandLedgerHash", proof_root / "commands.jsonl"
    )
    return MaterializedTrace(path=proof_root, manifest=manifest, report=report)


async def materialize_execution_trace_from_request_id(
    request_id: str,
    *,
    out: str | Path | None = None,
    auth_headers: dict[str, str] | None = None,
    base_url: str | None = None,
    session_factory: Callable[[], Any] = aiohttp.ClientSession,
) -> MaterializedTrace:
    resolved_base_url = base_url or default_api_base_url()
    response = await _fetch_json(
        f"{resolved_base_url}/remote-dispatch/responses/{request_id}",
        auth_headers=auth_headers
        if auth_headers is not None
        else default_auth_headers(),
        session_factory=session_factory,
    )
    response_content = response.get("response")
    if not isinstance(response_content, dict):
        raise ValueError(
            f"Remote dispatch response {request_id} has no response object"
        )
    context = response_content.get("executionTraceContext")
    if not isinstance(context, dict):
        raise ValueError(
            f"Remote dispatch response {request_id} has no executionTraceContext"
        )
    return await materialize_execution_trace_context(
        context,
        out=out,
        label=f"request-{request_id}",
        source_run={
            "type": "remote-dispatch",
            "authority": "remote-dispatch-response-api",
            "requestId": request_id,
            "status": response.get("status"),
            "createdAt": response.get("createdAt"),
            "completedAt": response.get("completedAt"),
            "responseHash": _sha256_json(response),
        },
        auth_headers=auth_headers,
        base_url=resolved_base_url,
        session_factory=session_factory,
    )


def append_command(
    proof_root: Path,
    *,
    command: str,
    status: str,
    command_id: str | None = None,
    exit_code: int | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    taints: list[str] | None = None,
    ids: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    row = {
        "schemaVersion": 1,
        "commandId": command_id or f"cmd_{uuid.uuid4().hex}",
        "runId": proof_root.name,
        "command": command,
        "status": status,
        "exitCode": _status_exit_code(status) if exit_code is None else exit_code,
        "startedAt": now,
        "completedAt": now,
        "ids": ids or {},
        "inputs": inputs or {},
        "artifacts": artifacts or [],
        "warnings": warnings or [],
        "taints": taints or [],
    }
    commands_path = proof_root / "commands.jsonl"
    commands_path.parent.mkdir(parents=True, exist_ok=True)
    with commands_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _scan_redaction(root: Path) -> dict[str, Any]:
    scanned_text_files: list[str] = []
    skipped_binary_files: list[str] = []
    findings: list[dict[str, Any]] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = _relative(path, root)
        if path.suffix.lower() in BINARY_SCAN_SUFFIXES:
            skipped_binary_files.append(relative_path)
            continue
        scanned_text_files.append(relative_path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        text_lower = text.lower()
        for marker_index, marker in enumerate(_SIGNED_URL_PATTERNS, start=1):
            if marker in text_lower:
                findings.append(
                    {
                        "code": "signed_url_leak",
                        "severity": "failure",
                        "path": relative_path,
                        "markerId": f"signed-url-marker-{marker_index}",
                    }
                )
        for pattern_index, pattern in enumerate(_SECRET_PATTERNS, start=1):
            if pattern.search(text):
                findings.append(
                    {
                        "code": "secret_leak",
                        "severity": "failure",
                        "path": relative_path,
                        "patternId": f"secret-pattern-{pattern_index}",
                    }
                )
        for pattern_index, pattern in enumerate(_SELF_REVIEW_PATTERNS, start=1):
            if pattern.search(text):
                findings.append(
                    {
                        "code": "workflow_self_review_marker",
                        "severity": "taint",
                        "path": relative_path,
                        "patternId": f"self-review-pattern-{pattern_index}",
                    }
                )
        for pattern_index, pattern in enumerate(_STATIC_ANSWER_PATTERNS, start=1):
            if pattern.search(text):
                findings.append(
                    {
                        "code": "static_answer_marker",
                        "severity": "failure",
                        "path": relative_path,
                        "patternId": f"static-answer-pattern-{pattern_index}",
                    }
                )

    status = (
        "failed"
        if any(finding["severity"] == "failure" for finding in findings)
        else ("tainted" if findings else "passed")
    )
    return {
        "schemaVersion": 1,
        "status": status,
        "scannedTextFiles": scanned_text_files,
        "skippedBinaryFiles": skipped_binary_files,
        "findings": findings,
    }


def _write_redaction_report(root: Path) -> dict[str, Any]:
    report = _scan_redaction(root)
    _write_json(root / REDACTION_REPORT_JSON, report)
    (root / REDACTION_REPORT_MD).write_text(
        "# Redaction Report\n\n"
        f"Status: {report['status']}\n\n"
        f"Scanned text files: {len(report['scannedTextFiles'])}\n\n"
        f"Skipped binary files: {len(report['skippedBinaryFiles'])}\n\n"
        f"Findings: {len(report['findings'])}\n",
        encoding="utf-8",
    )
    return report


def _update_manifest_hash(root: Path, field_name: str, path: Path) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return
    loaded = _load_json(manifest_path)
    if not isinstance(loaded, dict):
        return
    loaded[field_name] = _sha256_file(path)
    _write_json(manifest_path, loaded)


def score_proof_root(proof_root: str | Path, *, write: bool = True) -> dict[str, Any]:
    root = Path(proof_root)
    failures: list[dict[str, Any]] = []
    taints: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    manifest_path = root / "manifest.json"
    manifest_kind = "trace"
    if manifest_path.exists():
        loaded_for_kind = _load_json(manifest_path)
        if isinstance(loaded_for_kind, dict):
            manifest_kind = str(loaded_for_kind.get("proofRootKind") or "trace")
    is_browser_workbench_root = manifest_kind == "browser-workbench"
    required_files = (
        ("manifest.json", "commands.jsonl", "cleanup/status.json")
        if is_browser_workbench_root
        else REQUIRED_PROOF_FILES
    )

    for relative_path in required_files:
        if not (root / relative_path).exists():
            failures.append({"code": "missing_required_file", "path": relative_path})

    artifact_rows: list[dict[str, Any]] = []
    manifest: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    resolved_trace: dict[str, Any] | None = None
    expected_artifact_keys: set[str] = set()

    context_path = root / "trace" / "context.json"
    resolved_path = root / "trace" / "resolved.json"
    index_path = root / "trace" / "artifacts" / "index.jsonl"
    browser_index_path = root / "browser" / "artifacts.jsonl"
    if manifest_path.exists():
        loaded = _load_json(manifest_path)
        manifest = loaded if isinstance(loaded, dict) else None
    if context_path.exists():
        loaded = _load_json(context_path)
        context = loaded if isinstance(loaded, dict) else None
    if resolved_path.exists():
        loaded = _load_json(resolved_path)
        resolved_trace = loaded if isinstance(loaded, dict) else None

    if manifest is None and manifest_path.exists():
        failures.append({"code": "manifest_not_object"})
    if context is None and context_path.exists():
        failures.append({"code": "trace_context_not_object"})
    if resolved_trace is None and resolved_path.exists():
        failures.append({"code": "resolved_trace_not_object"})

    if context is not None and resolved_trace is not None:
        trace_id = context.get("traceId")
        resolved_context = resolved_trace.get("context")
        resolved_manifest = resolved_trace.get("manifest")
        if (
            isinstance(resolved_context, dict)
            and resolved_context.get("traceId") != trace_id
        ):
            failures.append({"code": "resolved_context_trace_id_mismatch"})
        if (
            isinstance(resolved_manifest, dict)
            and resolved_manifest.get("traceId") != trace_id
        ):
            failures.append({"code": "resolved_manifest_trace_id_mismatch"})
        if not any(
            isinstance(resolved_trace.get(name), list) and resolved_trace.get(name)
            for name in ("events", "scopes", "frames")
        ):
            failures.append({"code": "empty_resolved_trace"})
        for collection_name, id_name in (
            ("events", "eventId"),
            ("scopes", "scopeId"),
            ("frames", "frameId"),
        ):
            rows = resolved_trace.get(collection_name)
            if rows is None:
                failures.append(
                    {
                        "code": "resolved_collection_missing",
                        "collection": collection_name,
                    }
                )
                continue
            if not isinstance(rows, list):
                failures.append(
                    {
                        "code": "resolved_collection_not_list",
                        "collection": collection_name,
                    }
                )
                continue
            for row in rows:
                if not isinstance(row, dict):
                    failures.append(
                        {
                            "code": "resolved_row_not_object",
                            "collection": collection_name,
                        }
                    )
                    continue
                if row.get("traceId") != trace_id:
                    failures.append(
                        {
                            "code": "resolved_row_trace_id_mismatch",
                            "collection": collection_name,
                            "rowId": row.get(id_name),
                        }
                    )
        expected_artifact_keys = _collect_resolved_trace_artifact_keys(
            context, resolved_trace
        )

    if manifest is not None:
        manifest_context = manifest.get("traceContext")
        source_run = manifest.get("sourceRun")
        if not is_browser_workbench_root:
            if not isinstance(source_run, dict):
                failures.append({"code": "source_run_missing"})
            else:
                source_failures, source_taints = _source_run_problems(source_run)
                for code in source_failures:
                    failures.append(
                        {
                            "code": code,
                            "status": source_run.get("status"),
                        }
                    )
                for code in source_taints:
                    taints.append(
                        {
                            "code": code,
                            "status": source_run.get("status"),
                            "authority": source_run.get("authority"),
                        }
                    )
        if context is not None and manifest_context != context:
            failures.append({"code": "manifest_context_mismatch"})
        if context is not None and manifest.get("traceId") not in {
            None,
            context.get("traceId"),
        }:
            failures.append({"code": "manifest_trace_id_mismatch"})
        if context is not None:
            if not manifest.get("traceContextHash"):
                failures.append({"code": "manifest_context_hash_missing"})
            elif manifest.get("traceContextHash") != _sha256_json(context):
                failures.append({"code": "manifest_context_hash_mismatch"})
        if resolved_trace is not None:
            if not manifest.get("resolvedTraceHash"):
                failures.append({"code": "manifest_resolved_trace_hash_missing"})
            elif manifest.get("resolvedTraceHash") != _sha256_json(resolved_trace):
                failures.append({"code": "manifest_resolved_trace_hash_mismatch"})
        if index_path.exists():
            if not manifest.get("artifactIndexHash"):
                failures.append({"code": "manifest_artifact_index_hash_missing"})
            elif manifest.get("artifactIndexHash") != _sha256_file(index_path):
                failures.append({"code": "manifest_artifact_index_hash_mismatch"})
        if browser_index_path.exists():
            if not manifest.get("browserArtifactIndexHash"):
                failures.append(
                    {"code": "manifest_browser_artifact_index_hash_missing"}
                )
            elif manifest.get("browserArtifactIndexHash") != _sha256_file(
                browser_index_path
            ):
                failures.append(
                    {"code": "manifest_browser_artifact_index_hash_mismatch"}
                )
        commands_path = root / "commands.jsonl"
        if commands_path.exists():
            if not manifest.get("commandLedgerHash"):
                failures.append({"code": "manifest_command_ledger_hash_missing"})
            elif manifest.get("commandLedgerHash") != _sha256_file(commands_path):
                failures.append({"code": "manifest_command_ledger_hash_mismatch"})
        for failure in manifest.get("failures") or []:
            failures.append({"code": "manifest_failure", "failure": failure})
        if manifest.get("status") == "tainted":
            taints.append({"code": "manifest_tainted"})
        for taint in manifest.get("taints") or []:
            taints.append({"code": "manifest_taint", "taint": taint})
        for status_field in ("traceContextStatus", "traceManifestStatus"):
            if _is_failed_status(manifest.get(status_field)):
                failures.append(
                    {
                        "code": "trace_status_failed",
                        "field": status_field,
                        "status": manifest.get(status_field),
                    }
                )
    if context is not None and _is_failed_status(context.get("status")):
        failures.append(
            {
                "code": "trace_status_failed",
                "field": "context.status",
                "status": context.get("status"),
            }
        )
    if resolved_trace is not None:
        resolved_manifest = resolved_trace.get("manifest")
        if isinstance(resolved_manifest, dict) and _is_failed_status(
            resolved_manifest.get("status")
        ):
            failures.append(
                {
                    "code": "trace_status_failed",
                    "field": "resolved.manifest.status",
                    "status": resolved_manifest.get("status"),
                }
            )

    if index_path.exists():
        artifact_rows = _load_jsonl(index_path)
        seen_artifact_keys: set[str] = set()
        for row in artifact_rows:
            local_path_value = row.get("localPath")
            source_key = row.get("sourceS3Key")
            if row.get("downloadStatus") == "failed":
                failures.append(
                    {
                        "code": "artifact_download_failed",
                        "sourceS3Key": source_key,
                        "role": row.get("role"),
                    }
                )
            if not isinstance(local_path_value, str) or not local_path_value:
                failures.append({"code": "artifact_missing_local_path", "row": row})
                continue
            if not isinstance(source_key, str) or not source_key:
                failures.append(
                    {"code": "artifact_missing_source_key", "path": local_path_value}
                )
            elif expected_artifact_keys and source_key not in expected_artifact_keys:
                failures.append(
                    {
                        "code": "artifact_source_not_in_resolved_trace",
                        "path": local_path_value,
                        "sourceS3Key": source_key,
                    }
                )
            elif source_key:
                seen_artifact_keys.add(source_key)
            if os.path.isabs(local_path_value):
                failures.append(
                    {"code": "artifact_absolute_path", "path": local_path_value}
                )
            local_path = root / local_path_value
            if not local_path.resolve().is_relative_to(root.resolve()):
                failures.append(
                    {"code": "artifact_path_escape", "path": local_path_value}
                )
                continue
            if not local_path.exists():
                failures.append(
                    {"code": "artifact_file_missing", "path": local_path_value}
                )
                continue
            expected_sha = row.get("sha256")
            actual_sha = _sha256_file(local_path)
            if expected_sha != actual_sha:
                failures.append(
                    {
                        "code": "artifact_hash_mismatch",
                        "path": local_path_value,
                        "expected": expected_sha,
                        "actual": actual_sha,
                    }
                )
            if "downloadUrl" in row:
                failures.append(
                    {"code": "signed_url_persisted", "path": local_path_value}
                )
        missing_artifact_keys = expected_artifact_keys - seen_artifact_keys
        for source_key in sorted(missing_artifact_keys):
            failures.append(
                {
                    "code": "resolved_artifact_not_downloaded",
                    "sourceS3Key": source_key,
                }
            )
    browser_artifact_rows: list[dict[str, Any]] = []
    if browser_index_path.exists():
        browser_artifact_rows = _load_jsonl(browser_index_path)
        for row in browser_artifact_rows:
            local_path_value = row.get("path")
            if not isinstance(local_path_value, str) or not local_path_value:
                failures.append({"code": "browser_artifact_missing_path", "row": row})
                continue
            if os.path.isabs(local_path_value):
                failures.append(
                    {"code": "browser_artifact_absolute_path", "path": local_path_value}
                )
                continue
            local_path = root / local_path_value
            if not local_path.resolve().is_relative_to(root.resolve()):
                failures.append(
                    {"code": "browser_artifact_path_escape", "path": local_path_value}
                )
                continue
            if not local_path.exists():
                failures.append(
                    {"code": "browser_artifact_file_missing", "path": local_path_value}
                )
                continue
            expected_sha = row.get("sha256")
            if expected_sha != _sha256_file(local_path):
                failures.append(
                    {
                        "code": "browser_artifact_hash_mismatch",
                        "path": local_path_value,
                    }
                )

    redaction_report = _write_redaction_report(root) if write else _scan_redaction(root)
    for finding in redaction_report["findings"]:
        if finding["severity"] == "failure":
            failures.append(
                {
                    "code": finding["code"],
                    "path": finding["path"],
                }
            )
        elif finding["severity"] == "taint":
            taints.append(
                {
                    "code": finding["code"],
                    "path": finding["path"],
                }
            )

    commands_path = root / "commands.jsonl"
    if commands_path.exists():
        command_rows = _load_jsonl(commands_path)
        needs_review = False
        if not command_rows:
            failures.append({"code": "empty_command_ledger"})
        materialize_commands = [
            row for row in command_rows if row.get("command") == "trace.materialize"
        ]
        browser_commands = [
            row
            for row in command_rows
            if isinstance(row.get("command"), str)
            and (
                str(row.get("command")).startswith("browser.")
                or str(row.get("command")).startswith("env.")
            )
        ]
        if not materialize_commands and not is_browser_workbench_root:
            failures.append({"code": "missing_materialize_command"})
        if is_browser_workbench_root and not browser_commands:
            failures.append({"code": "missing_browser_workbench_command"})
        for row in materialize_commands:
            if row.get("status") not in CLEAN_COMMAND_STATUSES:
                continue
            ids = row.get("ids")
            if not isinstance(ids, dict):
                failures.append({"code": "materialize_command_ids_missing"})
                continue
            if manifest is not None:
                for field_name, manifest_field in (
                    ("traceId", "traceId"),
                    ("contextHash", "traceContextHash"),
                    ("resolvedTraceHash", "resolvedTraceHash"),
                    ("artifactIndexHash", "artifactIndexHash"),
                ):
                    if not ids.get(field_name):
                        failures.append(
                            {
                                "code": "materialize_command_id_missing",
                                "field": field_name,
                            }
                        )
                    elif ids.get(field_name) != manifest.get(manifest_field):
                        failures.append(
                            {
                                "code": "materialize_command_id_mismatch",
                                "field": field_name,
                            }
                        )
        for row in command_rows:
            if not row.get("commandId"):
                failures.append(
                    {
                        "code": "command_missing_command_id",
                        "command": row.get("command"),
                    }
                )
            if not row.get("runId"):
                failures.append(
                    {"code": "command_missing_run_id", "command": row.get("command")}
                )
            row_status = row.get("status")
            if (
                row.get("command") == "trace.materialize"
                and row_status not in CLEAN_COMMAND_STATUSES
            ):
                taints.append(
                    {
                        "code": "materialize_command_not_clean",
                        "status": row_status,
                    }
                )
            elif _is_failed_status(row_status):
                taints.append({"code": "prior_command_failed", "status": row_status})
            elif row_status not in CLEAN_COMMAND_STATUSES:
                needs_review = True
                warnings.append(
                    {
                        "code": "command_status_needs_review",
                        "command": row.get("command"),
                        "status": row_status,
                    }
                )
            if (
                row.get("command")
                in {"browser.click-nrd", "browser.fill-nrd", "browser.select-nrd"}
                and row_status in CLEAN_COMMAND_STATUSES
            ):
                ids = row.get("ids")
                if not isinstance(ids, dict) or not ids.get("postSnapshotId"):
                    needs_review = True
                    warnings.append(
                        {
                            "code": "browser_action_post_snapshot_missing",
                            "command": row.get("command"),
                        }
                    )
            row_command = row.get("command")
            for warning in row.get("warnings") or []:
                if row_command in {"score", "verify"}:
                    continue
                warnings.append(
                    {
                        "code": "command_warning",
                        "command": row_command,
                        "warning": warning,
                    }
                )
            for taint in row.get("taints") or []:
                taints.append({"code": "command_taint", "taint": taint})
            artifacts = row.get("artifacts")
            if isinstance(artifacts, list):
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        failures.append(
                            {
                                "code": "command_artifact_not_object",
                                "command": row.get("command"),
                            }
                        )
                        continue
                    artifact_path = artifact.get("path")
                    if not isinstance(artifact_path, str) or not artifact_path:
                        failures.append(
                            {
                                "code": "command_artifact_missing_path",
                                "command": row.get("command"),
                            }
                        )
                        continue
                    if os.path.isabs(artifact_path):
                        failures.append(
                            {
                                "code": "command_artifact_absolute_path",
                                "path": artifact_path,
                            }
                        )
                        continue
                    local_path = root / artifact_path
                    if not local_path.resolve().is_relative_to(root.resolve()):
                        failures.append(
                            {
                                "code": "command_artifact_path_escape",
                                "path": artifact_path,
                            }
                        )
                        continue
                    if not local_path.exists():
                        failures.append(
                            {
                                "code": "command_artifact_file_missing",
                                "path": artifact_path,
                            }
                        )
                        continue
                    expected_hash = artifact.get("sha256")
                    if expected_hash is not None and expected_hash != _sha256_file(
                        local_path
                    ):
                        failures.append(
                            {
                                "code": "command_artifact_hash_mismatch",
                                "path": artifact_path,
                            }
                        )
            ids = row.get("ids")
            if isinstance(ids, dict):
                report_hash_fields = {
                    "scoreHash": ("scorePath", "scorer/score.json"),
                    "proofStatusHash": (
                        "proofStatusPath",
                        "reports/proof-status.json",
                    ),
                    "verificationReportHash": (
                        "verificationReportPath",
                        "reports/verification-report.json",
                    ),
                }
                for field, (
                    path_field,
                    default_relative_path,
                ) in report_hash_fields.items():
                    if field not in ids:
                        continue
                    path_override = ids.get(path_field)
                    relative_path = (
                        path_override
                        if isinstance(path_override, str) and path_override
                        else default_relative_path
                    )
                    report_path = root / relative_path
                    if not report_path.exists():
                        failures.append(
                            {
                                "code": "report_hash_target_missing",
                                "field": field,
                                "path": relative_path,
                            }
                        )
                    elif ids[field] != _sha256_file(report_path):
                        failures.append(
                            {
                                "code": "report_hash_mismatch",
                                "field": field,
                                "path": relative_path,
                            }
                        )
    else:
        needs_review = False

    cleanup_path = root / "cleanup" / "status.json"
    if cleanup_path.exists():
        cleanup = _load_json(cleanup_path)
        if not isinstance(cleanup, dict):
            failures.append({"code": "cleanup_status_not_object"})
        else:
            cleanup_status = cleanup.get("status")
            if cleanup_status == "failed":
                taints.append({"code": "cleanup_failed"})
            elif is_browser_workbench_root and cleanup_status != "passed":
                needs_review = True
                warnings.append(
                    {
                        "code": "cleanup_status_not_terminal",
                        "status": cleanup_status,
                    }
                )
    else:
        taints.append({"code": "cleanup_status_missing"})

    status = (
        "failed"
        if failures
        else "tainted"
        if taints
        else "needs_review"
        if needs_review
        else "passed"
    )
    score = {
        "schemaVersion": 1,
        "status": status,
        "proofRoot": str(root),
        "failures": failures,
        "taints": taints,
        "warnings": warnings,
        "artifactCount": len(artifact_rows) + len(browser_artifact_rows),
        "structuralOnly": is_browser_workbench_root,
    }
    if write:
        score_command_id = f"cmd_{uuid.uuid4().hex}"
        score_path = root / "scorer" / "score.json"
        proof_status_path = root / "reports" / "proof-status.json"
        score_history_relative_path = f"scorer/history/{score_command_id}.json"
        proof_status_history_relative_path = (
            f"reports/history/proof-status-{score_command_id}.json"
        )
        _write_json(score_path, score)
        _write_json(root / score_history_relative_path, score)
        (root / "scorer" / "score.md").write_text(
            f"# Score\n\nStatus: {status}\n\nFailures: {len(failures)}\n\nTaints: {len(taints)}\n",
            encoding="utf-8",
        )
        _write_json(proof_status_path, score)
        _write_json(root / proof_status_history_relative_path, score)
        (root / "reports" / "proof-status.md").write_text(
            f"# Proof Status\n\nStatus: {status}\n",
            encoding="utf-8",
        )
        append_command(
            root,
            command_id=score_command_id,
            command="score",
            status=status,
            artifacts=[
                _artifact_ref(root, score_history_relative_path, "score"),
                _artifact_ref(root, proof_status_history_relative_path, "proof-status"),
            ],
            warnings=_warning_codes(warnings),
            taints=[taint["code"] for taint in taints],
            ids={
                "scorePath": score_history_relative_path,
                "scoreHash": _sha256_file(root / score_history_relative_path),
                "proofStatusPath": proof_status_history_relative_path,
                "proofStatusHash": _sha256_file(
                    root / proof_status_history_relative_path
                ),
            },
        )
        _update_manifest_hash(root, "commandLedgerHash", root / "commands.jsonl")
        _write_redaction_report(root)
    return score


def verify_proof_root(proof_root: str | Path, *, write: bool = True) -> dict[str, Any]:
    score = score_proof_root(proof_root, write=write)
    verified = {
        **score,
        "verified": score["status"] == "passed",
    }
    if write:
        root = Path(proof_root)
        verify_command_id = f"cmd_{uuid.uuid4().hex}"
        verification_report_path = root / "reports" / "verification-report.json"
        verification_history_relative_path = (
            f"reports/history/verification-report-{verify_command_id}.json"
        )
        _write_json(verification_report_path, verified)
        (root / "reports" / "verification-report.md").write_text(
            f"# Verification Report\n\nVerified: {str(verified['verified']).lower()}\n\nStatus: {score['status']}\n",
            encoding="utf-8",
        )
        final_redaction_report = _write_redaction_report(root)
        if final_redaction_report["findings"]:
            final_status = (
                "failed"
                if any(
                    finding["severity"] == "failure"
                    for finding in final_redaction_report["findings"]
                )
                else "tainted"
            )
            verified = {
                **verified,
                "status": final_status,
                "verified": False,
                "redactionFindingsAfterVerify": final_redaction_report["findings"],
            }
            _write_json(verification_report_path, verified)
            (root / "reports" / "verification-report.md").write_text(
                f"# Verification Report\n\nVerified: false\n\nStatus: {final_status}\n",
                encoding="utf-8",
            )
        _write_json(root / verification_history_relative_path, verified)
        append_command(
            root,
            command_id=verify_command_id,
            command="verify",
            status=verified["status"],
            artifacts=[
                _artifact_ref(
                    root, verification_history_relative_path, "verification-report"
                ),
            ],
            warnings=_warning_codes(score["warnings"]),
            taints=[taint["code"] for taint in score["taints"]],
            ids={
                "verificationReportPath": verification_history_relative_path,
                "verificationReportHash": _sha256_file(
                    root / verification_history_relative_path
                ),
            },
        )
        _update_manifest_hash(root, "commandLedgerHash", root / "commands.jsonl")
        _write_redaction_report(root)
    return verified

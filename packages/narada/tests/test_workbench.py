from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from narada.cli import main
from narada.workbench import (
    materialize_execution_trace_context,
    score_proof_root,
    verify_proof_root,
)

TRACE_CONTEXT = {
    "type": "executionTraceContext",
    "label": "Trace",
    "traceId": "trace-1",
    "executionTraceS3Key": "user-test/recording-trace-1/execution-trace/index.json",
}


class _FakeResponse:
    def __init__(
        self, *, payload: dict[str, Any] | None = None, body: bytes = b""
    ) -> None:
        self._payload = payload
        self._body = body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        assert self._payload is not None
        return self._payload

    async def read(self) -> bytes:
        return self._body


class _FakeSession:
    def __init__(self) -> None:
        self.downloads = {
            "https://signed.example.test/index.json?X-Amz-Signature=secret": json.dumps(
                {"traceId": "trace-1"}
            ).encode(),
            "https://signed.example.test/frame.html?X-Amz-Signature=secret": b"<html>ok</html>",
            "https://signed.example.test/screenshot.png?X-Amz-Signature=secret": b"png",
        }

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        assert url.endswith("/execution-trace/resolve")
        assert kwargs["json"]["executionTraceContext"]["traceId"] == "trace-1"
        return _FakeResponse(
            payload={
                "context": TRACE_CONTEXT,
                "resolvedTrace": {
                    "context": TRACE_CONTEXT,
                    "manifest": {
                        "traceId": "trace-1",
                        "segmentId": "segment-1",
                        "label": "Trace",
                        "status": "completed",
                        "artifacts": {},
                    },
                    "segments": [],
                    "events": [
                        {
                            "traceId": "trace-1",
                            "eventId": "event-1",
                            "sequence": 1,
                            "timestamp": 1,
                            "kind": "test.event",
                        }
                    ],
                    "scopes": [],
                    "timeline_index": {
                        "traceId": "trace-1",
                        "generatedAt": 1,
                        "events": [],
                        "scopes": [],
                        "frames": [
                            {
                                "label": "frame_1",
                                "frameId": "frame-1",
                                "frameS3Key": "user-test/recording-trace-1/execution-trace/frame.json",
                                "eventLabels": [],
                                "reason": "test",
                                "page": {
                                    "url": "https://example.test",
                                    "title": "Example",
                                },
                            }
                        ],
                        "aliases": {},
                    },
                    "frames": [
                        {
                            "traceId": "trace-1",
                            "frameId": "frame-1",
                            "sequence": 1,
                            "capturedAt": 1,
                            "reason": "test",
                            "page": {"url": "https://example.test", "title": "Example"},
                            "eventIds": ["event-1"],
                            "htmlS3Key": "user-test/recording-trace-1/execution-trace/frame.html",
                            "screenshotS3Key": "user-test/recording-trace-1/execution-trace/screenshot.png",
                        }
                    ],
                },
                "artifacts": [
                    {
                        "role": "manifest",
                        "s3Key": TRACE_CONTEXT["executionTraceS3Key"],
                        "downloadUrl": "https://signed.example.test/index.json?X-Amz-Signature=secret",
                        "contentType": "application/json",
                        "sensitive": True,
                    },
                    {
                        "role": "html",
                        "s3Key": "user-test/recording-trace-1/execution-trace/frame.html",
                        "downloadUrl": "https://signed.example.test/frame.html?X-Amz-Signature=secret",
                        "contentType": "text/html",
                        "sensitive": True,
                        "frameId": "frame-1",
                        "label": "frame_1",
                    },
                    {
                        "role": "screenshot",
                        "s3Key": "user-test/recording-trace-1/execution-trace/screenshot.png",
                        "downloadUrl": "https://signed.example.test/screenshot.png?X-Amz-Signature=secret",
                        "contentType": "image/png",
                        "sensitive": True,
                        "frameId": "frame-1",
                        "label": "frame_1",
                    },
                ],
            }
        )

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        del kwargs
        return _FakeResponse(body=self.downloads[url])


class _MissingArtifactSession(_FakeSession):
    def __init__(self) -> None:
        super().__init__()
        del self.downloads[
            "https://signed.example.test/frame.html?X-Amz-Signature=secret"
        ]


@pytest.mark.asyncio
async def test_materializer_writes_proof_root_without_signed_url_leaks(
    tmp_path: Path,
) -> None:
    result = await materialize_execution_trace_context(
        TRACE_CONTEXT,
        out=tmp_path,
        source_run={
            "type": "remote-dispatch",
            "authority": "agent-run-response",
            "status": "success",
            "requestId": "req-test",
        },
        auth_headers={"x-api-key": "test"},
        base_url="https://api.example.test/fast/v2",
        session_factory=_FakeSession,
    )

    assert result.path == tmp_path
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "trace" / "resolved.json").exists()
    assert (tmp_path / "reports" / "redaction-report.json").exists()
    assert (tmp_path / "trace" / "frames" / "frame-1" / "page.html").exists()
    assert (tmp_path / "trace" / "frames" / "frame-1" / "screenshot.png").exists()
    assert (tmp_path / "trace" / "frames" / "frame-1" / "summary.json").exists()
    assert (
        "X-Amz-Signature"
        not in (tmp_path / "trace" / "artifacts" / "index.jsonl").read_text()
    )

    score = score_proof_root(tmp_path)
    assert score["status"] == "passed"
    assert verify_proof_root(tmp_path)["verified"] is True


@pytest.mark.asyncio
async def test_materializer_records_missing_referenced_artifact_as_failed(
    tmp_path: Path,
) -> None:
    result = await materialize_execution_trace_context(
        TRACE_CONTEXT,
        out=tmp_path,
        source_run={
            "type": "remote-dispatch",
            "authority": "agent-run-response",
            "status": "success",
            "requestId": "req-test",
        },
        auth_headers={"x-api-key": "test"},
        base_url="https://api.example.test/fast/v2",
        session_factory=_MissingArtifactSession,
    )

    assert result.report["status"] == "failed"
    artifact_index = (tmp_path / "trace" / "artifacts" / "index.jsonl").read_text()
    assert "artifact_download_failed" not in artifact_index
    assert '"downloadStatus": "failed"' in artifact_index

    score = score_proof_root(tmp_path)
    assert score["status"] == "failed"
    assert any(
        failure["code"] == "artifact_download_failed" for failure in score["failures"]
    )
    assert verify_proof_root(tmp_path)["verified"] is False


@pytest.mark.asyncio
async def test_materializer_taints_preexisting_proof_root(tmp_path: Path) -> None:
    (tmp_path / "old-file.txt").write_text("old", encoding="utf-8")

    result = await materialize_execution_trace_context(
        TRACE_CONTEXT,
        out=tmp_path,
        source_run={
            "type": "remote-dispatch",
            "authority": "agent-run-response",
            "status": "success",
            "requestId": "req-test",
        },
        auth_headers={"x-api-key": "test"},
        base_url="https://api.example.test/fast/v2",
        session_factory=_FakeSession,
    )

    assert result.report["status"] == "tainted"
    score = score_proof_root(tmp_path)
    assert score["status"] == "tainted"
    assert any(taint["code"] == "manifest_taint" for taint in score["taints"])


@pytest.mark.asyncio
async def test_materializer_taints_missing_source_run_status(tmp_path: Path) -> None:
    result = await materialize_execution_trace_context(
        TRACE_CONTEXT,
        out=tmp_path,
        auth_headers={"x-api-key": "test"},
        base_url="https://api.example.test/fast/v2",
        session_factory=_FakeSession,
    )

    assert result.report["status"] == "tainted"
    score = score_proof_root(tmp_path)
    assert score["status"] == "tainted"
    assert any(
        taint["code"] == "source_run_status_unknown" for taint in score["taints"]
    )


def _write_clean_minimal_root(root: Path) -> None:
    (root / "trace" / "artifacts").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "cleanup").mkdir()
    context = TRACE_CONTEXT
    resolved = {
        "context": context,
        "manifest": {
            "traceId": context["traceId"],
            "segmentId": "segment-1",
            "label": "Trace",
            "status": "completed",
            "artifacts": {},
        },
        "segments": [],
        "events": [
            {
                "traceId": context["traceId"],
                "eventId": "event-1",
                "sequence": 1,
                "timestamp": 1,
                "kind": "test.event",
            }
        ],
        "scopes": [],
        "timeline_index": {
            "traceId": context["traceId"],
            "generatedAt": 1,
            "events": [],
            "scopes": [],
            "frames": [],
            "aliases": {},
        },
        "frames": [],
    }
    manifest_bytes = json.dumps({"traceId": context["traceId"]}).encode()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    (root / "trace" / "artifacts" / "manifest_1.json").write_bytes(manifest_bytes)
    context_hash = hashlib.sha256(
        json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    resolved_hash = hashlib.sha256(
        json.dumps(resolved, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (root / "trace" / "context.json").write_text(json.dumps(context), encoding="utf-8")
    (root / "trace" / "resolved.json").write_text(
        json.dumps(resolved), encoding="utf-8"
    )
    (root / "trace" / "events.jsonl").write_text(
        json.dumps(resolved["events"][0]) + "\n",
        encoding="utf-8",
    )
    (root / "trace" / "scopes.jsonl").write_text("", encoding="utf-8")
    (root / "trace" / "timeline.json").write_text(
        json.dumps(resolved["timeline_index"]),
        encoding="utf-8",
    )
    artifact_index = (
        json.dumps(
            {
                "role": "manifest",
                "sourceS3Key": context["executionTraceS3Key"],
                "localPath": "trace/artifacts/manifest_1.json",
                "sha256": manifest_hash,
                "downloadStatus": "downloaded",
            }
        )
        + "\n"
    )
    (root / "trace" / "artifacts" / "index.jsonl").write_text(
        artifact_index,
        encoding="utf-8",
    )
    artifact_index_hash = hashlib.sha256(artifact_index.encode()).hexdigest()
    command_ledger = (
        json.dumps(
            {
                "commandId": "cmd_test",
                "runId": root.name,
                "command": "trace.materialize",
                "status": "passed",
                "exitCode": 0,
                "ids": {
                    "traceId": context["traceId"],
                    "contextHash": context_hash,
                    "resolvedTraceHash": resolved_hash,
                    "artifactIndexHash": artifact_index_hash,
                },
            }
        )
        + "\n"
    )
    command_ledger_hash = hashlib.sha256(command_ledger.encode()).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "status": "materialized",
                "traceContext": context,
                "traceId": context["traceId"],
                "sourceRun": {
                    "type": "remote-dispatch",
                    "authority": "agent-run-response",
                    "status": "success",
                    "requestId": "req-test",
                },
                "traceContextHash": context_hash,
                "resolvedTraceHash": resolved_hash,
                "artifactIndexHash": artifact_index_hash,
                "commandLedgerHash": command_ledger_hash,
                "traceManifestStatus": "completed",
            }
        ),
        encoding="utf-8",
    )
    (root / "commands.jsonl").write_text(
        command_ledger,
        encoding="utf-8",
    )
    (root / "reports" / "materialization-report.json").write_text(
        "{}", encoding="utf-8"
    )
    (root / "reports" / "redaction-report.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "passed",
                "scannedTextFiles": [],
                "skippedBinaryFiles": [],
                "findings": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "cleanup" / "status.json").write_text(
        json.dumps({"status": "not_applicable"}),
        encoding="utf-8",
    )


def test_score_fails_signed_url_leak(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "leak.txt").write_text(
        "X-Amz-Signature=secret", encoding="utf-8"
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(failure["code"] == "signed_url_leak" for failure in score["failures"])
    redaction_report = json.loads(
        (tmp_path / "reports" / "redaction-report.json").read_text()
    )
    assert redaction_report["status"] == "failed"
    assert any(
        finding["code"] == "signed_url_leak" for finding in redaction_report["findings"]
    )
    assert "X-Amz-Signature" not in json.dumps(redaction_report)


def test_score_fails_missing_trace_file(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "resolved.json").unlink()

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure == {"code": "missing_required_file", "path": "trace/resolved.json"}
        for failure in score["failures"]
    )


def test_score_fails_empty_shell_root(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "resolved.json").write_text(
        json.dumps(
            {
                "context": TRACE_CONTEXT,
                "manifest": {"traceId": "trace-1", "status": "completed"},
                "events": [],
                "scopes": [],
                "frames": [],
            }
        ),
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "empty_resolved_trace" for failure in score["failures"]
    )


def test_score_fails_resolved_trace_id_mismatch(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    resolved = json.loads((tmp_path / "trace" / "resolved.json").read_text())
    resolved["manifest"]["traceId"] = "trace-other"
    (tmp_path / "trace" / "resolved.json").write_text(
        json.dumps(resolved), encoding="utf-8"
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "resolved_manifest_trace_id_mismatch"
        for failure in score["failures"]
    )


def test_score_fails_missing_referenced_artifact(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "artifacts" / "index.jsonl").write_text(
        json.dumps(
            {
                "role": "html",
                "localPath": "trace/frames/frame-1/page.html",
                "sha256": "missing",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "artifact_file_missing" for failure in score["failures"]
    )


def test_score_fails_missing_resolved_artifact_download(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "artifacts" / "index.jsonl").write_text("", encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "resolved_artifact_not_downloaded"
        for failure in score["failures"]
    )


def test_score_fails_foreign_artifact_source_key(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    artifact_path = tmp_path / "trace" / "artifacts" / "foreign.json"
    artifact_path.write_text("{}", encoding="utf-8")
    (tmp_path / "trace" / "artifacts" / "index.jsonl").write_text(
        json.dumps(
            {
                "role": "manifest",
                "sourceS3Key": "user-test/recording-other/execution-trace/index.json",
                "localPath": "trace/artifacts/foreign.json",
                "sha256": hashlib.sha256(b"{}").hexdigest(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "artifact_source_not_in_resolved_trace"
        for failure in score["failures"]
    )


def test_score_fails_artifact_path_escape(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "artifacts" / "index.jsonl").write_text(
        json.dumps(
            {
                "role": "html",
                "localPath": "../old-run/page.html",
                "sha256": "stale",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "artifact_path_escape" for failure in score["failures"]
    )


def test_score_fails_secret_leak(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "secret.txt").write_text(
        "Authorization: Bearer abc123",
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(failure["code"] == "secret_leak" for failure in score["failures"])


@pytest.mark.parametrize(
    "payload",
    [
        '{"plaintextKey": "abc123"}',
        '{"apiKey": "abc123"}',
        '{"accessToken": "abc123"}',
        '{"cookie": "sid=abc123"}',
        "token=abc123",
    ],
)
def test_score_fails_common_json_secret_fields(tmp_path: Path, payload: str) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "secret.json").write_text(payload, encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(failure["code"] == "secret_leak" for failure in score["failures"])


def test_score_write_false_does_not_mutate_redaction_report(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    redaction_path = tmp_path / "reports" / "redaction-report.json"
    before = redaction_path.read_text(encoding="utf-8")
    (tmp_path / "trace" / "secret.json").write_text(
        '{"plaintextKey": "abc123"}',
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path, write=False)

    assert score["status"] == "failed"
    assert redaction_path.read_text(encoding="utf-8") == before


def test_verify_redaction_report_covers_verification_artifacts(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)

    verify = verify_proof_root(tmp_path)

    redaction_report = json.loads(
        (tmp_path / "reports" / "redaction-report.json").read_text()
    )
    assert verify["verified"] is True
    assert "reports/verification-report.json" in redaction_report["scannedTextFiles"]
    assert "reports/verification-report.md" in redaction_report["scannedTextFiles"]


def test_score_fails_lowercase_signed_url_leak(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "leak.txt").write_text(
        "x-amz-signature=secret", encoding="utf-8"
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(failure["code"] == "signed_url_leak" for failure in score["failures"])


def test_score_fails_failed_trace_status(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    resolved = json.loads((tmp_path / "trace" / "resolved.json").read_text())
    resolved["manifest"]["status"] = "failed"
    (tmp_path / "trace" / "resolved.json").write_text(
        json.dumps(resolved), encoding="utf-8"
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "trace_status_failed" for failure in score["failures"]
    )


def test_score_fails_missing_source_run(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    del manifest["sourceRun"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(failure["code"] == "source_run_missing" for failure in score["failures"])


def test_score_fails_failed_source_run(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["sourceRun"]["status"] = "failed"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(failure["code"] == "source_run_failed" for failure in score["failures"])


def test_score_taints_unknown_source_run_status(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["sourceRun"]["status"] = "unknown"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "tainted"
    assert any(
        taint["code"] == "source_run_status_unknown" for taint in score["taints"]
    )


def test_score_taints_unverified_source_run_authority(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["sourceRun"]["authority"] = "caller-attested"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "tainted"
    assert any(
        taint["code"] == "source_run_authority_unverified" for taint in score["taints"]
    )
    assert verify_proof_root(tmp_path)["verified"] is False


def test_score_fails_non_terminal_source_run_status(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["sourceRun"]["status"] = "input-required"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "source_run_not_terminal" for failure in score["failures"]
    )


def test_score_fails_missing_manifest_hash(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    del manifest["resolvedTraceHash"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "manifest_resolved_trace_hash_missing"
        for failure in score["failures"]
    )


def test_score_fails_artifact_index_hash_mismatch(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["artifactIndexHash"] = "wrong"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "manifest_artifact_index_hash_mismatch"
        for failure in score["failures"]
    )


def test_score_fails_missing_command_ledger_hash(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    del manifest["commandLedgerHash"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "manifest_command_ledger_hash_missing"
        for failure in score["failures"]
    )


def test_score_fails_command_ledger_hash_mismatch(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    with (tmp_path / "commands.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"commandId": "cmd_extra", "status": "passed"}) + "\n")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "manifest_command_ledger_hash_mismatch"
        for failure in score["failures"]
    )


def test_score_fails_materialize_command_hash_mismatch(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    command = json.loads((tmp_path / "commands.jsonl").read_text().splitlines()[0])
    command["ids"]["resolvedTraceHash"] = "wrong"
    (tmp_path / "commands.jsonl").write_text(
        json.dumps(command) + "\n", encoding="utf-8"
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "materialize_command_id_mismatch"
        for failure in score["failures"]
    )


def test_score_fails_static_answer_marker(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "answers.py").write_text(
        "VALUE_RULES = {}",
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "static_answer_marker" for failure in score["failures"]
    )


def test_score_fails_renamed_answer_map_marker(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "answers.py").write_text(
        "ANSWER_MAP = {}",
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "static_answer_marker" for failure in score["failures"]
    )


def test_score_fails_missing_materialize_command(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "commands.jsonl").write_text(
        json.dumps({"command": "score", "status": "passed"}) + "\n",
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "missing_materialize_command"
        for failure in score["failures"]
    )


def test_score_taints_workflow_self_review_marker(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "self-review.json").write_text(
        json.dumps({"workflowSelfApproved": True}),
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "tainted"
    assert any(
        taint["code"] == "workflow_self_review_marker" for taint in score["taints"]
    )


def test_score_taints_renamed_self_review_marker(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "self-review.json").write_text(
        json.dumps({"approvedBy": "workflow", "reviewStatus": "accepted"}),
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "tainted"
    assert any(
        taint["code"] == "workflow_self_review_marker" for taint in score["taints"]
    )


def test_score_taints_cleanup_failure(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "cleanup" / "status.json").write_text(
        json.dumps({"status": "failed"}),
        encoding="utf-8",
    )

    score = score_proof_root(tmp_path)

    assert score["status"] == "tainted"
    assert any(taint["code"] == "cleanup_failed" for taint in score["taints"])


def test_score_taints_prior_failed_command(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    with (tmp_path / "commands.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "commandId": "cmd_failed",
                    "runId": tmp_path.name,
                    "command": "trace.materialize",
                    "status": "failed",
                }
            )
            + "\n"
        )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["commandLedgerHash"] = hashlib.sha256(
        (tmp_path / "commands.jsonl").read_bytes()
    ).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "tainted"
    assert any(
        taint["code"] == "materialize_command_not_clean" for taint in score["taints"]
    )


def test_cli_score_returns_nonzero_for_failed_root(tmp_path: Path) -> None:
    _write_clean_minimal_root(tmp_path)
    (tmp_path / "trace" / "leak.txt").write_text(
        "X-Amz-Credential=secret", encoding="utf-8"
    )

    assert main(["workbench", "score", str(tmp_path), "--json"]) == 1


def test_cli_materialize_context_file_uses_materializer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import narada.cli as cli_module

    context_file = tmp_path / "context.json"
    context_file.write_text(
        json.dumps({"executionTraceContext": TRACE_CONTEXT}), encoding="utf-8"
    )
    calls: list[dict[str, Any]] = []

    async def fake_materialize(context: dict[str, Any], **kwargs: Any) -> Any:
        calls.append({"context": context, **kwargs})

        class _Result:
            path = tmp_path / "proof"
            report = {"status": "passed", "artifactCount": 0, "warnings": []}

        return _Result()

    monkeypatch.setattr(
        cli_module, "materialize_execution_trace_context", fake_materialize
    )

    assert (
        main(
            [
                "workbench",
                "trace",
                "materialize",
                "--context-file",
                str(context_file),
                "--out",
                str(tmp_path / "proof"),
                "--json",
            ]
        )
        == 0
    )
    assert calls[0]["context"] == TRACE_CONTEXT
    assert calls[0]["source_run"] is None


def test_cli_materialize_context_file_with_source_status_is_caller_attested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import narada.cli as cli_module

    context_file = tmp_path / "context.json"
    context_file.write_text(
        json.dumps({"executionTraceContext": TRACE_CONTEXT}), encoding="utf-8"
    )
    calls: list[dict[str, Any]] = []

    async def fake_materialize(context: dict[str, Any], **kwargs: Any) -> Any:
        calls.append({"context": context, **kwargs})

        class _Result:
            path = tmp_path / "proof"
            report = {"status": "tainted", "artifactCount": 0, "warnings": []}

        return _Result()

    monkeypatch.setattr(
        cli_module, "materialize_execution_trace_context", fake_materialize
    )

    assert (
        main(
            [
                "workbench",
                "trace",
                "materialize",
                "--context-file",
                str(context_file),
                "--source-status",
                "completed",
                "--source-request-id",
                "req-123",
                "--json",
            ]
        )
        == 1
    )
    assert calls[0]["source_run"] == {
        "type": "external",
        "authority": "caller-attested",
        "status": "completed",
        "requestId": "req-123",
    }


def test_cli_materialize_request_id_uses_request_materializer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import narada.cli as cli_module

    calls: list[dict[str, Any]] = []

    async def fake_materialize(request_id: str, **kwargs: Any) -> Any:
        calls.append({"request_id": request_id, **kwargs})

        class _Result:
            path = tmp_path / "proof"
            report = {"status": "passed", "artifactCount": 0, "warnings": []}

        return _Result()

    monkeypatch.setattr(
        cli_module,
        "materialize_execution_trace_from_request_id",
        fake_materialize,
    )

    assert (
        main(
            [
                "workbench",
                "trace",
                "materialize",
                "--request-id",
                "req-123",
                "--json",
            ]
        )
        == 0
    )
    assert calls[0]["request_id"] == "req-123"


def test_cli_redacts_sensitive_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import narada.cli as cli_module

    context_file = tmp_path / "context.json"
    context_file.write_text(
        json.dumps({"executionTraceContext": TRACE_CONTEXT}), encoding="utf-8"
    )

    async def fake_materialize(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ValueError(
            "failed https://signed.example.test/file?X-Amz-Signature=secret "
            "Authorization: Bearer abc123"
        )

    monkeypatch.setattr(
        cli_module, "materialize_execution_trace_context", fake_materialize
    )

    assert (
        main(
            [
                "workbench",
                "trace",
                "materialize",
                "--context-file",
                str(context_file),
                "--json",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "X-Amz-Signature" not in captured.err
    assert "Bearer abc123" not in captured.err
    assert "[REDACTED" in captured.err

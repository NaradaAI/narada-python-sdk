from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from narada import (
    Agent,
    ExecutionTraceClient,
    ExecutionTraceError,
    RemoteBrowserEnvironment,
)


def canonical_archive(trace_id="rdtrace-v1-req-1", *, extra=None):
    contents = {
        "context.json": json.dumps({"schemaVersion": 1, "traceId": trace_id}),
        "index.json": json.dumps({"schemaVersion": 1, "traceId": trace_id}),
        "events.jsonl": "",
        "segments.jsonl": "",
        "scopes.jsonl": "",
        "timeline-index.json": "{}",
        "timeline.md": "# Fixture trace\n",
        "frames/frame_0001/page.html": "<p>Fixture business result</p>",
    }
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
        if extra is not None:
            archive.writestr(*extra)
    return data.getvalue()


@pytest.fixture
def api(tmp_path):
    state = SimpleNamespace(
        posts=[],
        api_auth=[],
        archive_auth=[],
        archive_cookies=[],
        archive=None,
        trace_status="ready",
        http_status=200,
        poll_status="success",
        response_seen_before_download=[],
        run_dir=None,
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, value, *, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            assert self.path == "/remote-dispatch"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.api_auth.append(self.headers.get("x-api-key"))
            state.posts.append(body)
            self.reply({"requestId": f"req-{len(state.posts)}"})

        def do_GET(self):
            if self.path.startswith("/archive/"):
                state.archive_auth.append(self.headers.get("x-api-key"))
                state.archive_cookies.append(self.headers.get("Cookie"))
                request_id = self.path.split("/")[-1].split("?")[0]
                content = (
                    state.archive
                    if state.archive is not None
                    else canonical_archive(f"rdtrace-v1-{request_id}")
                )
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            state.api_auth.append(self.headers.get("x-api-key"))
            if self.path == "/sdk/config":
                self.reply(
                    {
                        "executionTrace": {
                            "allowed": True,
                            "denialReason": None,
                            "supportedModes": ["client"],
                        }
                    }
                )
            elif self.path.endswith("/execution-trace"):
                request_id = self.path.split("/")[-2]
                if state.run_dir is not None:
                    state.response_seen_before_download.append(
                        (
                            state.run_dir
                            / "artifacts/requests"
                            / request_id
                            / "response.json"
                        ).is_file()
                    )
                self.reply(
                    {
                        "status": state.trace_status,
                        "download": {
                            "downloadUrl": f"{state.url}/archive/{request_id}?signature=fixture-signed-secret",
                            "expiresInSeconds": 300,
                        },
                    },
                    status=state.http_status,
                )
            elif self.path.startswith("/remote-dispatch/responses/"):
                request_id = self.path.split("/")[-1]
                request_body = state.posts[int(request_id.split("-")[-1]) - 1]
                output = {"type": "text", "content": "business-result"}
                if "criticContext" in request_body:
                    output = {
                        "type": "structured",
                        "content": {"narada_validation_passed": True},
                    }
                self.reply(
                    {
                        "status": state.poll_status,
                        "response": {
                            "text": "business-result",
                            "output": output,
                            "executionTraceContext": {
                                "schemaVersion": 1,
                                "traceId": f"rdtrace-v1-{request_id}",
                                "executionTraceS3Key": f"user-fixture/recording-rdtrace-v1-{request_id}/execution-trace/index.json",
                            },
                        },
                        "usage": {"actions": 1, "credits": 1},
                        "createdAt": "2026-01-01T00:00:00Z",
                        "completedAt": "2026-01-01T00:00:01Z",
                    }
                )
            else:
                self.reply({}, status=404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def active_run(tmp_path):
    run_dir = tmp_path / "0123456789abcdef0123456789abcdef"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({"schemaVersion": 1, "runId": run_dir.name, "status": "running"})
    )
    (run_dir / "output.log").touch()
    (run_dir / "artifacts").mkdir()
    return run_dir


def client(api):
    return ExecutionTraceClient(
        base_url=api.url, auth_headers={"x-api-key": "fixture-api-secret"}
    )


def run_child(api, run_dir, *, critic=False, retry_request=None):
    script = """
import asyncio, json, os, narada
from pathlib import Path
from narada import Agent, RemoteBrowserEnvironment
async def main():
    env = RemoteBrowserEnvironment(browser_window_id="fixture-window")
    if os.environ.get("RETRY_REQUEST"):
        result = await env.execution_traces.fetch(request_id=os.environ["RETRY_REQUEST"], destination=Path(os.environ["RETRY_DESTINATION"]))
        print(json.dumps({"status": result.status}))
        return
    result = await Agent(environment=env).run("Complete the fixture", critic={} if os.environ.get("USE_CRITIC") else None)
    print(json.dumps({"requestId": result.request_id, "text": result.text, "status": result.status, "traceId": result.execution_trace_context["traceId"], "criticId": result.critic_result.request_id if result.critic_result else None, "sdkFile": narada.__file__}))
asyncio.run(main())
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(NARADA_API_KEY="fixture-api-secret", NARADA_API_BASE_URL=api.url)
    if retry_request:
        environment.pop("NARADA_RUN_DIR", None)
        environment.update(
            RETRY_REQUEST=retry_request,
            RETRY_DESTINATION=str(
                run_dir / "artifacts/requests" / retry_request / "execution-trace"
            ),
        )
    else:
        environment["NARADA_RUN_DIR"] = str(run_dir)
    if critic:
        environment["USE_CRITIC"] = "1"
    completed = subprocess.run(
        [os.environ.get("NARADA_TEST_PYTHON", sys.executable), "-c", script],
        cwd=run_dir.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "fixture-api-secret" not in completed.stdout + completed.stderr
    assert "fixture-signed-secret" not in completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def test_subprocess_records_primary_and_critic_response_first(api, tmp_path):
    api.run_dir = active_run(tmp_path)
    result = run_child(api, api.run_dir, critic=True)
    assert result["requestId"] == "req-1"
    assert result["criticId"] == "req-2"
    assert all(body["requireExecutionTrace"] is True for body in api.posts)
    assert api.response_seen_before_download == [True, True]
    assert api.archive_auth == [None, None]
    assert api.archive_cookies == [None, None]
    for number in (1, 2):
        directory = api.run_dir / f"artifacts/requests/req-{number}"
        assert (directory / "execution-trace/index.json").is_file()
        receipt = json.loads((directory / "evidence.json").read_text())
        assert receipt["status"] == "complete"
        assert receipt["parentRequestId"] == ("req-1" if number == 2 else None)
        assert (
            "fixture-signed-secret"
            not in (directory / "response.json").read_text()
            + (directory / "evidence.json").read_text()
        )
    if os.environ.get("NARADA_TEST_PYTHON"):
        assert "site-packages" in result["sdkFile"]
        assert "local-workflow-sdk/packages" not in result["sdkFile"]


@pytest.mark.parametrize("business_status", ["success", "error"])
def test_subprocess_evidence_failure_preserves_business_and_retry_never_dispatches(
    api, tmp_path, business_status
):
    api.run_dir = active_run(tmp_path)
    api.archive = b"truncated archive"
    api.poll_status = business_status
    result = run_child(api, api.run_dir)
    assert result["text"] == "business-result"
    assert result["status"] == business_status
    directory = api.run_dir / "artifacts/requests/req-1"
    assert (
        json.loads((directory / "response.json").read_text())["status"]
        == business_status
    )
    assert json.loads((directory / "evidence.json").read_text())["status"] == "failed"
    assert not (directory / "execution-trace").exists()
    api.archive = None
    assert run_child(api, api.run_dir, retry_request="req-1")["status"] == "complete"
    assert len(api.posts) == 1


@pytest.mark.asyncio
async def test_explicit_capture_response_context_and_capability(api, monkeypatch):
    monkeypatch.delenv("NARADA_RUN_DIR", raising=False)
    monkeypatch.setenv("NARADA_API_BASE_URL", api.url)
    env = RemoteBrowserEnvironment(
        browser_window_id="fixture-window", api_key="fixture-api-secret"
    )
    response = await Agent(environment=env).run("fixture", require_execution_trace=True)
    assert response.execution_trace_context["traceId"] == "rdtrace-v1-req-1"
    assert api.posts[0]["requireExecutionTrace"] is True
    assert (await env.execution_traces.capability()).allowed
    assert (
        api.archive_auth == []
    )  # explicit capture alone does not opt into disk writes


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "unavailable"])
async def test_nonready_download_publishes_nothing(api, tmp_path, state):
    api.trace_status = state
    destination = tmp_path / "trace"
    result = await client(api).fetch(request_id="req-1", destination=destination)
    assert result.status == state
    assert not destination.exists()
    assert api.posts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "C:/drive",
        "a\\escape",
        "frames/a:stream",
        "frames/CON.txt",
        "frames/trailing.",
        "INDEX.JSON",
    ],
)
async def test_unsafe_archive_never_publishes(api, tmp_path, path):
    api.archive = canonical_archive(extra=(path, "unsafe"))
    destination = tmp_path / "trace"
    with pytest.raises(ExecutionTraceError):
        await client(api).fetch(request_id="req-1", destination=destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".narada-trace-*"))
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.asyncio
async def test_symlink_and_expansion_limit_rejected(api, tmp_path, monkeypatch):
    symlink = zipfile.ZipInfo("link")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    api.archive = canonical_archive(extra=(symlink, "../outside"))
    with pytest.raises(ExecutionTraceError, match="unsupported_archive_entry"):
        await client(api).fetch(request_id="req-1", destination=tmp_path / "trace")
    import narada.execution_traces as traces

    monkeypatch.setattr(traces, "_MAX_EXTRACTED_BYTES", 100)
    api.archive = canonical_archive()
    with pytest.raises(ExecutionTraceError, match="archive_too_large"):
        await client(api).fetch(request_id="req-1", destination=tmp_path / "trace")


@pytest.mark.asyncio
async def test_identity_and_existing_destination_preserved(api, tmp_path):
    destination = tmp_path / "trace"
    with pytest.raises(ExecutionTraceError, match="trace_identity_mismatch"):
        await client(api).fetch(
            request_id="req-1", destination=destination, expected_trace_id="different"
        )
    destination.mkdir()
    (destination / "customer.txt").write_text("keep")
    with pytest.raises(ExecutionTraceError, match="destination_exists"):
        await client(api).fetch(request_id="req-1", destination=destination)
    assert (destination / "customer.txt").read_text() == "keep"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["_MAX_ARCHIVE_BYTES", "_MAX_FILES"])
async def test_download_and_file_count_limits(api, tmp_path, monkeypatch, limit):
    import narada.execution_traces as traces

    monkeypatch.setattr(traces, limit, 1)
    with pytest.raises(ExecutionTraceError, match="archive_too_large"):
        await client(api).fetch(request_id="req-1", destination=tmp_path / "trace")
    assert not (tmp_path / "trace").exists()
    assert not list(tmp_path.glob(".narada-trace-*"))


@pytest.mark.asyncio
async def test_missing_canonical_files_and_http_denial(api, tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("index.json", "{}")
    api.archive = data.getvalue()
    with pytest.raises(ExecutionTraceError, match="incomplete_archive"):
        await client(api).fetch(request_id="req-1", destination=tmp_path / "trace")
    api.http_status = 403
    with pytest.raises(ExecutionTraceError, match="denied") as error:
        await client(api).fetch(request_id="req-1", destination=tmp_path / "trace")
    assert "fixture-signed-secret" not in str(error.value)
    assert not (tmp_path / "trace").exists()


@pytest.mark.parametrize(
    "failure",
    ["status", "runId", "schemaVersion", "missing-output", "symlink", "relative"],
)
def test_invalid_run_binding_fails_before_dispatch(tmp_path, monkeypatch, failure):
    run_dir = active_run(tmp_path)
    manifest_path = run_dir / "manifest.json"
    if failure in ("status", "runId", "schemaVersion"):
        value = json.loads(manifest_path.read_text())
        value[failure] = {"status": "complete", "runId": "wrong", "schemaVersion": 2}[
            failure
        ]
        manifest_path.write_text(json.dumps(value))
    elif failure == "missing-output":
        (run_dir / "output.log").unlink()
    elif failure == "symlink":
        (run_dir / "artifacts").rmdir()
        (run_dir / "artifacts").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv(
        "NARADA_RUN_DIR", run_dir.name if failure == "relative" else str(run_dir)
    )
    with pytest.raises(ValueError, match="valid active Narada run"):
        RemoteBrowserEnvironment(
            browser_window_id="fixture", api_key="fixture-api-secret"
        )


def test_sdk_requires_normal_api_key_without_exposing_value(monkeypatch):
    monkeypatch.delenv("NARADA_API_KEY", raising=False)
    monkeypatch.delenv("NARADA_RUN_DIR", raising=False)
    monkeypatch.setenv("NARADA_PLUGIN_API_KEY", "fixture-plugin-secret")
    with pytest.raises(KeyError) as error:
        RemoteBrowserEnvironment(browser_window_id="fixture-window")
    assert "NARADA_API_KEY" in str(error.value)
    assert "fixture-plugin-secret" not in str(error.value)

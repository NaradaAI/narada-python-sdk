"""Real HTTP/subprocess evidence flow plus archive publication boundaries."""

import io
import json
import os
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from narada import ExecutionTraceClient, ExecutionTraceError


def archive_bytes(trace_id="rdtrace-v1-req-1", extra=None):
    identity = json.dumps({"schemaVersion": 1, "traceId": trace_id})
    files = dict.fromkeys(
        "events.jsonl segments.jsonl scopes.jsonl timeline-index.json timeline.md".split(),
        "",
    )
    files.update({"context.json": identity, "index.json": identity})
    if extra:
        files[extra] = "unsafe"
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return data.getvalue()


@pytest.fixture
def api(tmp_path):
    state = SimpleNamespace(
        posts=[], archive=None, status="ready", business="success", auth=[], saved=[]
    )
    state.run = tmp_path / ("a" * 32)
    (state.run / "artifacts").mkdir(parents=True)
    (state.run / "output.log").touch()
    (state.run / "manifest.json").write_text(
        json.dumps({"schemaVersion": 1, "runId": state.run.name, "status": "running"})
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, value):
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            assert self.path == "/remote-dispatch"
            assert self.headers.get("x-api-key") == "fixture-api-secret"
            state.posts.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            self.reply({"requestId": f"req-{len(state.posts)}"})

        def do_GET(self):
            request_id = self.path.split("/")[-1]
            if self.path.startswith("/archive/"):
                state.auth.append(
                    (self.headers.get("x-api-key"), self.headers.get("Cookie"))
                )
                self.reply(
                    state.archive
                    if state.archive is not None
                    else archive_bytes(f"rdtrace-v1-{request_id}")
                )
            elif self.path.endswith("/execution-trace"):
                request_id = self.path.split("/")[-2]
                state.saved.append(
                    (
                        state.run / f"artifacts/requests/{request_id}/response.json"
                    ).is_file()
                )
                self.reply(
                    {
                        "status": state.status,
                        "download": {
                            "downloadUrl": f"{state.url}/archive/{request_id}",
                            "expiresInSeconds": 60,
                        },
                    }
                )
            else:
                output = {"type": "text", "content": "done"}
                if "criticContext" in state.posts[int(request_id.split("-")[-1]) - 1]:
                    output = {
                        "type": "structured",
                        "content": {"narada_validation_passed": True},
                    }
                self.reply(
                    {
                        "status": state.business,
                        "createdAt": "2026-01-01T00:00:00Z",
                        "completedAt": "2026-01-01T00:00:01Z",
                        "response": {
                            "text": "done",
                            "output": output,
                            "executionTraceContext": {
                                "schemaVersion": 1,
                                "traceId": f"rdtrace-v1-{request_id}",
                                "executionTraceS3Key": f"user-fixture/recording-rdtrace-v1-{request_id}/execution-trace/index.json",
                            },
                        },
                        "usage": {"actions": 1, "credits": 1},
                    }
                )

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


def client(api):
    return ExecutionTraceClient(
        base_url=api.url, auth_headers={"x-api-key": "fixture-api-secret"}
    )


@pytest.mark.parametrize(
    "business,broken", [("success", False), ("success", True), ("error", True)]
)
def test_subprocess_response_first_critic_and_fetch_only_retry(api, business, broken):
    api.business = business
    api.archive = b"broken ZIP" if broken else None
    environment = {
        **os.environ,
        "NARADA_API_KEY": "fixture-api-secret",
        "NARADA_API_BASE_URL": api.url,
        "NARADA_RUN_DIR": str(api.run),
    }
    environment.pop("PYTHONPATH", None)
    script = """
import asyncio, json, narada
async def main():
    env = narada.RemoteBrowserEnvironment(browser_window_id="fixture")
    result = await narada.Agent(environment=env).run("fixture", critic={})
    print(json.dumps({"status": result.status, "requestId": result.request_id, "sdk": narada.__file__}))
asyncio.run(main())
"""
    result = subprocess.run(
        [os.environ.get("NARADA_TEST_PYTHON", sys.executable), "-c", script],
        cwd=api.run,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "fixture-api-secret" not in result.stdout + result.stderr
    response = json.loads(result.stdout)
    assert response["status"] == business
    assert all(body["requireExecutionTrace"] for body in api.posts)
    assert all(api.saved) and api.auth and set(api.auth) == {(None, None)}
    if os.environ.get("NARADA_TEST_PYTHON"):
        assert "site-packages" in response["sdk"]
    for number in range(1, len(api.posts) + 1):
        directory = api.run / f"artifacts/requests/req-{number}"
        receipt = json.loads((directory / "evidence.json").read_text())
        assert receipt["status"] == ("failed" if broken else "complete")
        assert receipt["parentRequestId"] == ("req-1" if number == 2 else None)
        assert (
            json.loads((directory / "response.json").read_text())["status"] == business
        )
    if business == "success":
        assert len(api.posts) == 2  # Primary and critic both carry trace opt-in.
    if broken:
        import asyncio

        api.archive = None
        assert (
            asyncio.run(
                client(api).fetch(request_id="req-1", destination=api.run / "retry")
            ).status
            == "complete"
        )
        assert len(api.posts) == number  # Fetch did not redispatch either action.


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "unavailable"])
async def test_nonready_download(api, tmp_path, state):
    api.status = state
    result = await client(api).fetch(request_id="req-1", destination=tmp_path / "trace")
    assert result.status == state
    assert not (tmp_path / "trace").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["../escape", "C:/drive", "frames/CON.txt", "INDEX.JSON"]
)
async def test_unsafe_archive_never_publishes(api, tmp_path, path):
    api.archive = archive_bytes(extra=path)
    with pytest.raises(ExecutionTraceError):
        await client(api).fetch(request_id="req-1", destination=tmp_path / "trace")
    assert not (tmp_path / "trace").exists()
    assert not list(tmp_path.glob(".narada-trace-*"))


@pytest.mark.asyncio
async def test_identity_and_existing_destination(api, tmp_path):
    destination = tmp_path / "trace"
    with pytest.raises(ExecutionTraceError, match="trace_identity_mismatch"):
        await client(api).fetch(
            request_id="req-1", destination=destination, expected_trace_id="other"
        )
    destination.mkdir()
    (destination / "customer.txt").write_text("keep")
    with pytest.raises(ExecutionTraceError, match="destination_exists"):
        await client(api).fetch(request_id="req-1", destination=destination)
    assert (destination / "customer.txt").read_text() == "keep"

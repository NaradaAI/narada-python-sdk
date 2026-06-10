from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from narada.cli import main
from narada.studio import (
    AgentStudioWorkbenchClient,
    AgentStudioWorkbenchError,
    studio_delete,
    studio_diff,
    studio_export,
    studio_list,
    studio_run,
    studio_upsert_python,
)
from narada.workbench import _sha256_json, append_command
from narada_core.actions.models import AgentResponse, AgentUsage, StructuredOutput


def _python_item(*, code: str = "print('remote')") -> dict[str, Any]:
    return {
        "id": "item_1",
        "type": "file",
        "ownerEmail": "user@example.com",
        "ownerUid": "user_1",
        "ownerName": "User One",
        "name": "Smoke",
        "parentPath": "/",
        "fileType": "pythonAgent",
        "fileData": {"code": code, "variables": []},
        "sharedWithEmails": [],
        "requestedAccessByEmails": [],
        "isPublic": False,
        "createdAt": "2026-06-09T00:00:00Z",
        "updatedAt": "2026-06-09T00:00:00Z",
    }


class _FakeResponse:
    def __init__(
        self, *, status: int = 200, payload: dict[str, Any] | None = None
    ) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def text(self) -> str:
        return "" if self._payload is None else json.dumps(self._payload)


class _FakeStudioSession:
    existing_item: dict[str, Any] | None = _python_item()
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def __init__(self) -> None:
        self.calls = self.__class__.calls

    async def __aenter__(self) -> "_FakeStudioSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("GET", url, kwargs))
        parsed = urlsplit(url)
        if parsed.path.endswith("/agent-studio/items") and parsed.query:
            return _FakeResponse(
                payload={"items": [self.existing_item] if self.existing_item else []}
            )
        if parsed.path.endswith("/agent-studio/resolve-path"):
            query = parse_qs(parsed.query)
            if query.get("path") == ["/missing"]:
                return _FakeResponse(status=404, payload={"detail": "not found"})
            if self.existing_item is None:
                return _FakeResponse(status=404, payload={"detail": "not found"})
            return _FakeResponse(payload={"item": self.existing_item})
        if parsed.path.endswith("/agent-studio/items/item_1"):
            if self.existing_item is None:
                return _FakeResponse(status=404, payload={"detail": "not found"})
            return _FakeResponse(payload={"item": self.existing_item})
        return _FakeResponse(status=500, payload={"detail": f"unexpected GET {url}"})

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("POST", url, kwargs))
        parsed = urlsplit(url)
        if parsed.path.endswith("/agent-studio/items"):
            body = kwargs["json"]
            self.__class__.existing_item = _python_item(code=body["fileData"]["code"])
            return _FakeResponse(payload={"id": "item_created"})
        if parsed.path.endswith("/agent-studio/items/item_1/update-file-data"):
            self.__class__.existing_item = _python_item(
                code=kwargs["json"]["fileData"]["code"]
            )
            return _FakeResponse(status=204)
        if parsed.path.endswith("/agent-studio/delete-items"):
            self.__class__.existing_item = None
            return _FakeResponse(status=204)
        return _FakeResponse(status=500, payload={"detail": f"unexpected POST {url}"})


@pytest.fixture(autouse=True)
def reset_fake_studio_session() -> None:
    _FakeStudioSession.existing_item = _python_item()
    _FakeStudioSession.calls = []


def _client() -> AgentStudioWorkbenchClient:
    return AgentStudioWorkbenchClient(
        auth_headers={"x-api-key": "test"},
        base_url="https://api.example.test/fast/v2",
        session_factory=_FakeStudioSession,
    )


@pytest.mark.asyncio
async def test_studio_list_writes_optional_proof_artifacts(tmp_path: Path) -> None:
    result = await studio_list(proof_root=tmp_path, client=_client())

    assert result.status == "passed"
    assert result.payload["items"][0]["id"] == "item_1"
    assert result.payload["items"][0]["fileType"] == "pythonAgent"
    assert "fileData" not in result.payload["items"][0]
    assert (tmp_path / "agent-studio" / "list.json").exists()
    list_artifact = json.loads(
        (tmp_path / "agent-studio" / "list.json").read_text(encoding="utf-8")
    )
    assert "fileData" not in list_artifact["items"][0]
    assert (tmp_path / "commands.jsonl").exists()
    command_row = json.loads((tmp_path / "commands.jsonl").read_text().splitlines()[0])
    assert command_row["inputs"]["apiBaseUrlOrigin"] == "https://api.example.test"
    assert command_row["inputs"]["authMode"] == "api-key"


@pytest.mark.asyncio
async def test_studio_export_writes_python_source_and_remote_item(
    tmp_path: Path,
) -> None:
    result = await studio_export(item_id="item_1", out=tmp_path, client=_client())

    assert result.status == "passed"
    assert (tmp_path / "agent-studio" / "items" / "item_1" / "export.py").read_text(
        encoding="utf-8"
    ) == "print('remote')"
    assert (tmp_path / "agent-studio" / "items" / "item_1" / "remote.json").exists()


@pytest.mark.asyncio
async def test_studio_diff_passes_when_local_matches_remote(tmp_path: Path) -> None:
    local = tmp_path / "agent.py"
    local.write_text("print('remote')", encoding="utf-8")

    result = await studio_diff(
        item_id="item_1",
        file=local,
        proof_root=tmp_path / "proof",
        client=_client(),
    )

    assert result.status == "passed"
    assert result.payload["matches"] is True


@pytest.mark.asyncio
async def test_studio_diff_returns_needs_review_when_local_differs(
    tmp_path: Path,
) -> None:
    local = tmp_path / "agent.py"
    local.write_text("print('local')", encoding="utf-8")

    result = await studio_diff(item_id="item_1", file=local, client=_client())

    assert result.status == "needs_review"
    assert result.payload["matches"] is False


@pytest.mark.asyncio
async def test_studio_upsert_python_dry_run_create_does_not_write(
    tmp_path: Path,
) -> None:
    _FakeStudioSession.existing_item = None
    local = tmp_path / "agent.py"
    local.write_text("print('created')", encoding="utf-8")

    result = await studio_upsert_python(
        name="missing",
        parent_path="/",
        file=local,
        apply=False,
        client=_client(),
    )

    assert result.status == "passed"
    assert result.payload["action"] == "create"
    assert result.payload["applied"] is False
    assert not any(call[0] == "POST" for call in _FakeStudioSession.calls)


@pytest.mark.asyncio
async def test_studio_upsert_python_apply_create_writes_lifecycle_report(
    tmp_path: Path,
) -> None:
    _FakeStudioSession.existing_item = None
    local = tmp_path / "agent.py"
    local.write_text("print('created')", encoding="utf-8")

    result = await studio_upsert_python(
        name="missing",
        parent_path="/",
        file=local,
        apply=True,
        proof_root=tmp_path / "proof",
        client=_client(),
    )

    assert result.status == "passed"
    assert result.payload["itemId"] == "item_created"
    assert (tmp_path / "proof" / "agent-studio" / "lifecycle-report.json").exists()


@pytest.mark.asyncio
async def test_studio_upsert_python_update_requires_expected_hash(
    tmp_path: Path,
) -> None:
    local = tmp_path / "agent.py"
    local.write_text("print('updated')", encoding="utf-8")

    with pytest.raises(AgentStudioWorkbenchError, match="expected hash"):
        await studio_upsert_python(
            name="Smoke",
            parent_path="/",
            file=local,
            apply=True,
            update_item_id="item_1",
            expected_remote_code_hash="wrong",
            client=_client(),
        )


@pytest.mark.asyncio
async def test_studio_upsert_python_update_applies_when_hash_matches(
    tmp_path: Path,
) -> None:
    local = tmp_path / "agent.py"
    local.write_text("print('updated')", encoding="utf-8")
    expected_hash = _sha256_json({"code": "print('remote')", "variables": []})

    result = await studio_upsert_python(
        name="Smoke",
        parent_path="/",
        file=local,
        apply=True,
        update_item_id="item_1",
        expected_remote_code_hash=expected_hash,
        client=_client(),
    )

    assert result.status == "passed"
    assert _FakeStudioSession.existing_item is not None
    assert _FakeStudioSession.existing_item["fileData"]["code"] == "print('updated')"


@pytest.mark.asyncio
async def test_studio_delete_requires_command_id_shape(tmp_path: Path) -> None:
    with pytest.raises(AgentStudioWorkbenchError, match="command id"):
        await studio_delete(
            item_id="item_1",
            expected_name="Smoke",
            created_by_command_id="not-a-command",
            proof_root=tmp_path,
            client=_client(),
        )


@pytest.mark.asyncio
async def test_studio_delete_requires_matching_upsert_command(tmp_path: Path) -> None:
    row = append_command(
        tmp_path,
        command="studio.upsert-python",
        status="passed",
        ids={"itemId": "item_1", "remoteCodeHash": None},
        inputs={"apply": True, "updateItemId": None},
    )

    result = await studio_delete(
        item_id="item_1",
        expected_name="Smoke",
        created_by_command_id=row["commandId"],
        proof_root=tmp_path,
        client=_client(),
    )

    assert result.status == "passed"
    assert _FakeStudioSession.existing_item is None
    assert (tmp_path / "agent-studio" / "cleanup.json").exists()


@pytest.mark.asyncio
async def test_studio_delete_rejects_update_command_provenance(tmp_path: Path) -> None:
    row = append_command(
        tmp_path,
        command="studio.upsert-python",
        status="passed",
        ids={"itemId": "item_1", "remoteCodeHash": "old-hash"},
        inputs={"apply": True, "updateItemId": "item_1"},
    )

    with pytest.raises(AgentStudioWorkbenchError, match="did not create"):
        await studio_delete(
            item_id="item_1",
            expected_name="Smoke",
            created_by_command_id=row["commandId"],
            proof_root=tmp_path,
            client=_client(),
        )

    assert _FakeStudioSession.existing_item is not None


@pytest.mark.asyncio
async def test_studio_run_requests_trace_capture_through_real_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEnvironment:
        instances: list["FakeEnvironment"] = []

        def __init__(self, **kwargs: Any) -> None:
            self._auth_headers = kwargs["auth_headers"]
            self._base_url = kwargs["base_url"]
            self.dispatch_kwargs: dict[str, Any] | None = None
            self.__class__.instances.append(self)

        async def _dispatch_request(self, **kwargs: Any) -> dict[str, Any]:
            self.dispatch_kwargs = kwargs
            return {
                "requestId": "req_1",
                "status": "success",
                "response": {
                    "text": "ok",
                    "output": {"type": "text", "content": "ok"},
                    "executionTraceContext": {
                        "executionTraceS3Key": "trace/index.json"
                    },
                },
                "usage": {"actions": 0, "credits": 0},
            }

    materialize_calls: list[dict[str, Any]] = []

    async def fake_materialize_execution_trace_context(*_: Any, **kwargs: Any) -> Any:
        materialize_calls.append(kwargs)
        root = Path(kwargs["out"])
        root.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(path=root)

    monkeypatch.setattr("narada.studio.Environment", FakeEnvironment)
    monkeypatch.setattr(
        "narada.tracing.materialize_execution_trace_context",
        fake_materialize_execution_trace_context,
    )

    result = await studio_run(
        item_id="item_1",
        proof_root=tmp_path,
        client=_client(),
    )

    assert result.status == "passed"
    fake_environment = FakeEnvironment.instances[0]
    assert fake_environment.dispatch_kwargs is not None
    assert fake_environment.dispatch_kwargs["capture_execution_trace"] is True
    assert len(materialize_calls) == 1
    assert materialize_calls[0]["out"] == tmp_path


@pytest.mark.asyncio
async def test_studio_run_writes_jsonable_response_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAgent:
        def __init__(self, **_: Any) -> None:
            pass

        async def run(self, prompt: str) -> AgentResponse[dict[str, Any]]:
            assert prompt == "/user@example.com/Smoke"
            from narada.tracing import get_active_trace_session

            active_trace_session = get_active_trace_session()
            assert active_trace_session is not None
            response = AgentResponse(
                request_id="req_1",
                status="success",
                text="ok",
                structured_output={"marker": "ok"},
                output=StructuredOutput(type="structured", content={"marker": "ok"}),
                usage=AgentUsage(actions=0, credits=0),
                execution_trace_context={"executionTraceS3Key": "trace/index.json"},
            )
            active_trace_session.register_response(
                response,
                auth_headers={},
                base_url="http://test.local/fast/v2",
            )
            return response

    async def fake_materialize_execution_trace_context(*_: Any, **kwargs: Any) -> Any:
        root = Path(kwargs["out"])
        root.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(path=root)

    monkeypatch.setattr("narada.studio.Agent", FakeAgent)
    monkeypatch.setattr(
        "narada.tracing.materialize_execution_trace_context",
        fake_materialize_execution_trace_context,
    )

    result = await studio_run(
        item_id="item_1",
        proof_root=tmp_path,
        client=_client(),
    )

    report = json.loads((tmp_path / "agent-studio" / "run.json").read_text())
    assert result.status == "passed"
    assert report["output"] == {"type": "structured", "content": {"marker": "ok"}}
    assert report["structuredOutput"] == {"marker": "ok"}


@pytest.mark.asyncio
async def test_studio_run_propagates_materializer_taint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAgent:
        def __init__(self, **_: Any) -> None:
            pass

        async def run(self, prompt: str) -> AgentResponse[dict[str, Any]]:
            assert prompt == "/user@example.com/Smoke"
            from narada.tracing import get_active_trace_session

            active_trace_session = get_active_trace_session()
            assert active_trace_session is not None
            response = AgentResponse(
                request_id="req_1",
                status="success",
                text="ok",
                structured_output=None,
                output={"type": "text", "content": "ok"},
                usage=AgentUsage(actions=0, credits=0),
                execution_trace_context={"executionTraceS3Key": "trace/index.json"},
            )
            active_trace_session.register_response(
                response,
                auth_headers={},
                base_url="http://test.local/fast/v2",
            )
            return response

    async def fake_materialize_execution_trace_context(*_: Any, **kwargs: Any) -> Any:
        root = Path(kwargs["out"])
        root.mkdir(parents=True, exist_ok=True)
        report_path = root / "reports" / "materialization-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"status": "tainted"}), encoding="utf-8")
        return SimpleNamespace(path=root, report={"status": "tainted"})

    monkeypatch.setattr("narada.studio.Agent", FakeAgent)
    monkeypatch.setattr(
        "narada.tracing.materialize_execution_trace_context",
        fake_materialize_execution_trace_context,
    )

    result = await studio_run(
        item_id="item_1",
        proof_root=tmp_path,
        client=_client(),
    )

    command_rows = [
        json.loads(line)
        for line in (tmp_path / "commands.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert result.status == "tainted"
    assert command_rows[-1]["command"] == "studio.run"
    assert command_rows[-1]["status"] == "tainted"
    assert command_rows[-1]["warnings"] == ["requires-active-client"]


def test_cli_studio_run_requires_trace() -> None:
    exit_code = main(
        [
            "workbench",
            "studio",
            "run",
            "--item-id",
            "item_1",
            "--json",
        ]
    )

    assert exit_code == 1

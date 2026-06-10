from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from narada.cli import main
from narada.project_sync import (
    GENERATED_HEADER,
    PROJECT_SYNC_GENERATOR,
    ProjectSyncError,
    build_project_package,
    extract_project_from_runtime,
    write_exported_project,
)
from narada.studio import (
    AgentStudioWorkbenchClient,
    AgentStudioWorkbenchError,
    studio_project_diff,
    studio_project_export,
    studio_sync_python_project,
)
from narada.workbench import _sha256_json


def _write_fixture_project(root: Path) -> None:
    (root / "helpers").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "runner.py").write_text(
        "\n".join(
            [
                "import json",
                "from pathlib import Path",
                "from helpers.math_utils import add",
                "config = json.loads((Path(__file__).parent / 'data' / 'config.json').read_text())",
                "print(f\"result={add(config['left'], config['right'])}\")",
            ]
        ),
        encoding="utf-8",
    )
    (root / "helpers" / "__init__.py").write_text("", encoding="utf-8")
    (root / "helpers" / "math_utils.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left + right\n",
        encoding="utf-8",
    )
    (root / "data" / "config.json").write_text(
        json.dumps({"left": 2, "right": 5}),
        encoding="utf-8",
    )


def _python_item(*, code: str, item_id: str = "item_1") -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "file",
        "ownerEmail": "user@example.com",
        "ownerUid": "user_1",
        "ownerName": "User One",
        "name": "Project",
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


class _FakeProjectSession:
    existing_item: dict[str, Any] | None = None
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def __init__(self) -> None:
        self.calls = self.__class__.calls

    async def __aenter__(self) -> "_FakeProjectSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("GET", url, kwargs))
        parsed = urlsplit(url)
        if parsed.path.endswith("/agent-studio/resolve-path"):
            query = parse_qs(parsed.query)
            if (
                query.get("path")
                in (
                    ["/Project"],
                    ["/folder/Project"],
                )
                and self.existing_item is not None
            ):
                return _FakeResponse(payload={"item": self.existing_item})
            return _FakeResponse(status=404, payload={"detail": "not found"})
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
            self.__class__.existing_item = _python_item(
                code=body["fileData"]["code"],
                item_id="item_created",
            )
            return _FakeResponse(payload={"id": "item_created"})
        if parsed.path.endswith("/agent-studio/items/item_1/update-file-data"):
            self.__class__.existing_item = _python_item(
                code=kwargs["json"]["fileData"]["code"]
            )
            return _FakeResponse(status=204)
        return _FakeResponse(status=500, payload={"detail": f"unexpected POST {url}"})


@pytest.fixture(autouse=True)
def reset_fake_project_session() -> None:
    _FakeProjectSession.existing_item = None
    _FakeProjectSession.calls = []


def _client() -> AgentStudioWorkbenchClient:
    return AgentStudioWorkbenchClient(
        auth_headers={"x-api-key": "test"},
        base_url="https://api.example.test/fast/v2",
        session_factory=_FakeProjectSession,
    )


def test_build_project_package_scans_allowed_files_and_excludes_caches(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ignored.pyc").write_bytes(b"ignored")

    package = build_project_package(local=tmp_path, entrypoint="runner.py")

    assert package.manifest["generator"] == PROJECT_SYNC_GENERATOR
    assert package.manifest["entrypoint"] == "runner.py"
    assert package.manifest["runtimeSha256"]
    assert GENERATED_HEADER in package.runtime_code
    assert {row["path"] for row in package.manifest["files"]} == {
        "data/config.json",
        "helpers/__init__.py",
        "helpers/math_utils.py",
        "runner.py",
    }


def test_build_project_package_rejects_unsafe_files(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path)
    (tmp_path / "secret.bin").write_bytes(b"\x00\x01")

    with pytest.raises(ProjectSyncError, match="Unsupported project file extension"):
        build_project_package(local=tmp_path, entrypoint="runner.py")


def test_build_project_package_rejects_symlink(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path)
    (tmp_path / "linked.py").symlink_to(tmp_path / "runner.py")

    with pytest.raises(ProjectSyncError, match="Symlinks"):
        build_project_package(local=tmp_path, entrypoint="runner.py")


def test_build_project_package_rejects_oversized_file(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path)

    with pytest.raises(ProjectSyncError, match="size limit"):
        build_project_package(
            local=tmp_path,
            entrypoint="runner.py",
            max_file_bytes=5,
        )


def test_generated_runtime_executes_fixture_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_fixture_project(tmp_path / "project")
    package = build_project_package(local=tmp_path / "project", entrypoint="runner.py")
    runtime_path = tmp_path / "generated-runtime.py"
    runtime_path.write_text(package.runtime_code, encoding="utf-8")

    runpy.run_path(str(runtime_path))

    captured = capsys.readouterr()
    assert "result=7" in captured.out


def test_generated_runtime_preserves_agent_studio_globals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "runner.py").write_text(
        "print('marker=' + EXTERNAL_MARKER)\n",
        encoding="utf-8",
    )
    package = build_project_package(local=project, entrypoint="runner.py")
    runtime_path = tmp_path / "generated-runtime.py"
    runtime_path.write_text(package.runtime_code, encoding="utf-8")

    runpy.run_path(str(runtime_path), init_globals={"EXTERNAL_MARKER": "visible"})

    captured = capsys.readouterr()
    assert "marker=visible" in captured.out


def test_extract_and_export_project_round_trips_files(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path / "project")
    package = build_project_package(local=tmp_path / "project", entrypoint="runner.py")

    manifest, files = extract_project_from_runtime(package.runtime_code)
    exported = write_exported_project(out=tmp_path / "exported", files=files)

    assert manifest["sourceTreeSha256"] == package.manifest["sourceTreeSha256"]
    assert {row["path"] for row in exported} == {
        "data/config.json",
        "helpers/__init__.py",
        "helpers/math_utils.py",
        "runner.py",
    }
    assert (tmp_path / "exported" / "helpers" / "math_utils.py").read_text(
        encoding="utf-8"
    ) == (tmp_path / "project" / "helpers" / "math_utils.py").read_text(
        encoding="utf-8"
    )


def test_project_export_refuses_non_empty_output_dir(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path / "project")
    package = build_project_package(local=tmp_path / "project", entrypoint="runner.py")
    _, files = extract_project_from_runtime(package.runtime_code)
    out = tmp_path / "exported"
    out.mkdir()
    (out / "local-edit.txt").write_text("do not overwrite me", encoding="utf-8")

    with pytest.raises(ProjectSyncError, match="not empty"):
        write_exported_project(out=out, files=files)


@pytest.mark.asyncio
async def test_sync_python_project_dry_run_writes_artifacts_without_remote_write(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path / "project")

    result = await studio_sync_python_project(
        local=tmp_path / "project",
        name="Project",
        parent_path="/",
        entrypoint="runner.py",
        apply=False,
        proof_root=tmp_path / "proof",
        client=_client(),
    )

    assert result.status == "passed"
    assert result.payload["applied"] is False
    assert not any(call[0] == "POST" for call in _FakeProjectSession.calls)
    assert (
        tmp_path / "proof" / "agent-studio" / "project-sync" / "generated-runtime.py"
    ).exists()


@pytest.mark.asyncio
async def test_sync_python_project_apply_create_writes_generated_runtime(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path / "project")

    result = await studio_sync_python_project(
        local=tmp_path / "project",
        name="Project",
        parent_path="/",
        entrypoint="runner.py",
        apply=True,
        proof_root=tmp_path / "proof",
        client=_client(),
    )

    assert result.status == "passed"
    assert result.payload["itemId"] == "item_created"
    assert _FakeProjectSession.existing_item is not None
    assert GENERATED_HEADER in _FakeProjectSession.existing_item["fileData"]["code"]


@pytest.mark.asyncio
async def test_sync_python_project_dry_run_existing_item_reports_guard_inputs(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path / "project")
    existing = build_project_package(local=tmp_path / "project", entrypoint="runner.py")
    _FakeProjectSession.existing_item = _python_item(
        code=existing.runtime_code,
        item_id="item_1",
    )

    result = await studio_sync_python_project(
        local=tmp_path / "project",
        name="Project",
        parent_path="/folder",
        entrypoint="runner.py",
        apply=False,
        proof_root=tmp_path / "proof",
        client=_client(),
    )

    assert result.status == "passed"
    assert result.payload["action"] == "update"
    assert result.payload["path"] == "/folder/Project"
    assert result.payload["requiresUpdateGuard"] is True
    assert result.payload["suggestedUpdateItemId"] == "item_1"
    assert result.payload["suggestedExpectedRemoteCodeHash"]
    assert not any(call[0] == "POST" for call in _FakeProjectSession.calls)


@pytest.mark.asyncio
async def test_sync_python_project_apply_update_requires_matching_remote_hash(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path / "project")
    existing = build_project_package(local=tmp_path / "project", entrypoint="runner.py")
    _FakeProjectSession.existing_item = _python_item(
        code=existing.runtime_code,
        item_id="item_1",
    )

    with pytest.raises(AgentStudioWorkbenchError, match="Remote code hash"):
        await studio_sync_python_project(
            local=tmp_path / "project",
            name="Project",
            parent_path="/",
            entrypoint="runner.py",
            apply=True,
            proof_root=tmp_path / "proof",
            update_item_id="item_1",
            expected_remote_code_hash="sha256:stale",
            client=_client(),
        )

    assert not any(
        call[0] == "POST" and call[1].endswith("/update-file-data")
        for call in _FakeProjectSession.calls
    )


@pytest.mark.asyncio
async def test_sync_python_project_apply_update_with_guard_updates_existing_item(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path / "project")
    existing = build_project_package(local=tmp_path / "project", entrypoint="runner.py")
    _FakeProjectSession.existing_item = _python_item(
        code=existing.runtime_code,
        item_id="item_1",
    )
    remote_hash = _sha256_json({"code": existing.runtime_code, "variables": []})
    (tmp_path / "project" / "helpers" / "math_utils.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left + right + 1\n",
        encoding="utf-8",
    )

    result = await studio_sync_python_project(
        local=tmp_path / "project",
        name="Project",
        parent_path="/",
        entrypoint="runner.py",
        apply=True,
        proof_root=tmp_path / "proof",
        update_item_id="item_1",
        expected_remote_code_hash=remote_hash,
        client=_client(),
    )

    assert result.status == "passed"
    assert result.payload["action"] == "update"
    assert result.payload["itemId"] == "item_1"
    assert any(
        call[0] == "POST" and call[1].endswith("/update-file-data")
        for call in _FakeProjectSession.calls
    )
    assert _FakeProjectSession.existing_item is not None
    assert (
        extract_project_from_runtime(
            _FakeProjectSession.existing_item["fileData"]["code"]
        )[0]["sourceTreeSha256"]
        == result.payload["sourceTreeSha256"]
    )


@pytest.mark.asyncio
async def test_sync_python_project_redaction_failure_skips_apply(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path / "project")
    (tmp_path / "project" / "runner.py").write_text(
        "print('NARADA_TEST_SECRET_SHOULD_FAIL')\n",
        encoding="utf-8",
    )

    result = await studio_sync_python_project(
        local=tmp_path / "project",
        name="Project",
        parent_path="/",
        entrypoint="runner.py",
        apply=True,
        proof_root=tmp_path / "proof",
        client=_client(),
    )

    assert result.status == "failed"
    assert result.payload["applied"] is False
    assert not any(call[0] == "POST" for call in _FakeProjectSession.calls)
    assert not (
        tmp_path / "proof" / "agent-studio" / "project-sync" / "generated-runtime.py"
    ).exists()
    assert not (
        tmp_path / "proof" / "agent-studio" / "project-sync" / "source-manifest.json"
    ).exists()


@pytest.mark.asyncio
async def test_project_diff_passes_and_detects_local_modification(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path / "project")
    package = build_project_package(local=tmp_path / "project", entrypoint="runner.py")
    _FakeProjectSession.existing_item = _python_item(code=package.runtime_code)

    passed = await studio_project_diff(
        local=tmp_path / "project",
        item_id="item_1",
        proof_root=tmp_path / "proof",
        client=_client(),
    )
    (tmp_path / "project" / "helpers" / "math_utils.py").write_text(
        "def add(left: int, right: int) -> int:\n    return 999\n",
        encoding="utf-8",
    )
    needs_review = await studio_project_diff(
        local=tmp_path / "project",
        item_id="item_1",
        proof_root=tmp_path / "proof-2",
        client=_client(),
    )

    assert passed.status == "passed"
    assert needs_review.status == "needs_review"
    assert needs_review.payload["modified"] == ["helpers/math_utils.py"]


@pytest.mark.asyncio
async def test_project_export_reconstructs_source_files(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path / "project")
    package = build_project_package(local=tmp_path / "project", entrypoint="runner.py")
    _FakeProjectSession.existing_item = _python_item(code=package.runtime_code)

    result = await studio_project_export(
        item_id="item_1",
        out=tmp_path / "exported",
        proof_root=tmp_path / "proof",
        client=_client(),
    )

    assert result.status == "passed"
    assert (tmp_path / "exported" / "runner.py").exists()
    assert (
        tmp_path
        / "proof"
        / "agent-studio"
        / "project-sync"
        / "exported-files"
        / "data"
        / "config.json"
    ).exists()


def test_project_export_rejects_non_workbench_generated_item() -> None:
    with pytest.raises(ProjectSyncError, match="not generated"):
        extract_project_from_runtime("print('plain script')\n")


def test_cli_json_failure_envelope_for_invalid_project(
    tmp_path: Path, capsys: Any
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "bad.bin").write_bytes(b"bad")

    exit_code = main(
        [
            "workbench",
            "studio",
            "sync-python-project",
            "--local",
            str(project),
            "--name",
            "Project",
            "--entrypoint",
            "runner.py",
            "--dry-run",
            "--proof-root",
            str(tmp_path / "proof"),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "failed"
    assert "Unsupported project file extension" in payload["error"]


def test_generated_runtime_manifest_hash_is_stable_for_remote_code_hash(
    tmp_path: Path,
) -> None:
    _write_fixture_project(tmp_path / "project")
    package = build_project_package(local=tmp_path / "project", entrypoint="runner.py")
    remote_hash = _sha256_json({"code": package.runtime_code, "variables": []})
    manifest, _files = extract_project_from_runtime(package.runtime_code)

    assert remote_hash
    assert manifest["runtimeSha256"] == package.manifest["runtimeSha256"]
    assert manifest["sourceTreeSha256"] == package.manifest["sourceTreeSha256"]

    (tmp_path / "project" / "data" / "config.json").write_text(
        json.dumps({"left": 9, "right": 5}),
        encoding="utf-8",
    )
    changed = build_project_package(local=tmp_path / "project", entrypoint="runner.py")

    assert changed.manifest["sourceTreeSha256"] != package.manifest["sourceTreeSha256"]
    assert _sha256_json({"code": changed.runtime_code, "variables": []}) != remote_hash

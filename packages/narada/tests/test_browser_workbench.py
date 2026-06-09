from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import narada.browser_workbench as browser_module
import pytest
from narada.browser_workbench import (
    browser_downloads,
    browser_find,
    browser_nrd_action,
    browser_screenshot,
    browser_selectors,
    browser_snapshot,
    env_close,
    env_open,
)
from narada.cli import main
from narada.workbench import score_proof_root, verify_proof_root
from narada_core.actions.models import (
    BrowserActionResponse,
    BrowserClickNrdRequest,
    BrowserDownloadsRequest,
    BrowserDownloadsResponse,
    BrowserPageSnapshotRequest,
    BrowserPageSnapshotResponse,
    BrowserScreenshotRequest,
    BrowserScreenshotResponse,
    GetUrlRequest,
    GetUrlResponse,
)


def _snapshot(snapshot_id: str = "snap_1") -> BrowserPageSnapshotResponse:
    return BrowserPageSnapshotResponse(
        snapshot_id=snapshot_id,
        url="https://fixture.test",
        title="Fixture",
        active=True,
        html=(
            '<body><button data-nrd="main:submit" aria-label="Submit order">'
            "Submit</button></body>"
        ),
        html_truncated=False,
        visible_text="Submit",
        visible_text_truncated=False,
        elements=[
            {
                "data_nrd": "main:submit",
                "frame_id": "main",
                "tag_name": "button",
                "text": "Submit",
                "aria_label": "Submit order",
                "interactive": True,
                "fingerprint": "abc123",
            }
        ],
        frames=[
            {
                "frame_id": "main",
                "title": "Fixture",
                "url": "https://fixture.test",
            }
        ],
        meta={"i": ["main:submit"], "h": [], "s": [], "sc": []},
    )


def _write_env_record(
    root: Path,
    *,
    env_id: str = "dev",
    browser_window_id: str = "window-1",
    api_base_url: str = "https://api.test",
    extra: dict[str, Any] | None = None,
) -> None:
    browser_module._browser_root(root, "browser-test")
    (root / "cleanup" / "status.json").write_text(
        json.dumps({"status": "passed", "browserEnvironmentStatus": "test"}),
        encoding="utf-8",
    )
    env_dir = root / "browser" / "environments"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / f"{env_id}.json").write_text(
        json.dumps(
            {
                "browserWindowId": browser_window_id,
                "apiBaseUrl": api_base_url,
                **(extra or {}),
            }
        ),
        encoding="utf-8",
    )


class _FakeRemoteEnvironment:
    calls: list[Any] = []
    fail_screenshot: bool = False
    download_path: Path | None = None
    stale_download_path: Path | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def _run_extension_action(
        self, request: Any, response_model: Any = None, **kwargs: Any
    ) -> Any:
        del kwargs
        self.__class__.calls.append(request)
        if isinstance(request, BrowserPageSnapshotRequest):
            return _snapshot(request.snapshot_id or "snap_1")
        if isinstance(request, BrowserClickNrdRequest):
            return BrowserActionResponse(
                post_snapshot=_snapshot("post_1") if request.post_snapshot else None
            )
        if isinstance(request, BrowserScreenshotRequest):
            if self.__class__.fail_screenshot:
                raise RuntimeError("Failed to take screenshot")
            content = base64.b64encode(b"png-bytes").decode("ascii").rstrip("=")
            return BrowserScreenshotResponse(
                base64_content=f"data:image/png;base64,{content}",
                name="screenshot.png",
                mime_type="image/png",
                timestamp="2026-06-09T00:00:00Z",
            )
        if isinstance(request, BrowserDownloadsRequest):
            if self.__class__.download_path is None:
                return BrowserDownloadsResponse(
                    downloads=[],
                    capture_supported=True,
                    warning="No completed Chrome downloads found.",
                )
            download_path = self.__class__.download_path
            downloads: list[dict[str, Any]] = []
            if self.__class__.stale_download_path is not None:
                stale_download_path = self.__class__.stale_download_path
                downloads.append(
                    {
                        "file_name": stale_download_path.name,
                        "file_size": stale_download_path.stat().st_size,
                        "state": "complete",
                        "exists": True,
                        "start_time": "2026-06-01T00:00:00Z",
                        "url": "https://fixture.test/old-download?token=secret",
                        "local_path": str(stale_download_path),
                    }
                )
            downloads.append(
                {
                    "file_name": download_path.name,
                    "file_size": download_path.stat().st_size,
                    "state": "complete",
                    "exists": True,
                    "start_time": request.started_after or "2026-06-09T00:00:01Z",
                    "url": "https://fixture.test/download?token=secret",
                    "local_path": str(download_path),
                }
            )
            return BrowserDownloadsResponse(
                downloads=downloads,
                capture_supported=True,
            )
        if isinstance(request, GetUrlRequest):
            return GetUrlResponse(url="https://fixture.test/current")
        if response_model is None:
            return None
        raise AssertionError(f"Unexpected request {request!r}")

    async def close(self, *, timeout: int | None = None) -> None:
        del timeout
        self.__class__.calls.append("close")


class _FakeLocalEnvironment:
    instances: list["_FakeLocalEnvironment"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.browser_window_id = "window-1"
        self.browser_process_id = 123
        self.__class__.instances.append(self)

    async def start(self) -> None:
        return None

    async def _stop_playwright(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_fake_remote_environment() -> None:
    _FakeRemoteEnvironment.calls = []
    _FakeRemoteEnvironment.download_path = None
    _FakeRemoteEnvironment.stale_download_path = None
    _FakeLocalEnvironment.instances = []


@pytest.mark.asyncio
async def test_browser_snapshot_writes_canonical_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path)

    result = await browser_snapshot(env_id="dev", proof_root=tmp_path)

    assert result.status == "passed"
    snapshot_id = result.payload["snapshotId"]
    assert (tmp_path / "browser" / "snapshots" / snapshot_id / "summary.json").exists()
    assert (
        tmp_path / "browser" / "snapshots" / snapshot_id / "simplified.html"
    ).exists()
    assert (tmp_path / "browser" / "page-snapshots.jsonl").exists()
    assert score_proof_root(tmp_path)["status"] == "passed"
    assert verify_proof_root(tmp_path)["verified"] is True


@pytest.mark.asyncio
async def test_browser_find_and_selectors_are_snapshot_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path)
    snapshot = await browser_snapshot(env_id="dev", proof_root=tmp_path)
    snapshot_id = snapshot.payload["snapshotId"]

    found = await browser_find(
        env_id="dev",
        snapshot_id=snapshot_id,
        proof_root=tmp_path,
        text="submit",
        interactive_only=True,
    )
    selectors = await browser_selectors(
        env_id="dev",
        snapshot_id=snapshot_id,
        frame_id="main",
        data_nrd="main:submit",
        proof_root=tmp_path,
    )

    assert found.payload["matchCount"] == 1
    assert selectors.payload["diagnostic"] is True
    assert selectors.payload["selectors"]["naradaId"] == "main:submit"


@pytest.mark.asyncio
async def test_browser_click_nrd_validates_snapshot_handle_and_writes_post_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path)
    snapshot = await browser_snapshot(env_id="dev", proof_root=tmp_path)

    result = await browser_nrd_action(
        env_id="dev",
        action="click",
        snapshot_id=snapshot.payload["snapshotId"],
        frame_id="main",
        data_nrd="main:submit",
        proof_root=tmp_path,
        post_snapshot=True,
    )

    assert result.status == "passed"
    assert result.payload["postSnapshotId"] == "post_1"
    assert isinstance(_FakeRemoteEnvironment.calls[-1], BrowserClickNrdRequest)


@pytest.mark.asyncio
async def test_browser_downloads_materializes_completed_local_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    proof_root = tmp_path / "proof"
    download_file = tmp_path / "source-downloads" / "fixture-download.txt"
    download_file.parent.mkdir()
    download_file.write_text("download bytes", encoding="utf-8")
    _FakeRemoteEnvironment.download_path = download_file
    _write_env_record(proof_root)

    result = await browser_downloads(env_id="dev", proof_root=proof_root)

    assert result.status == "passed"
    assert (
        result.payload["downloads"][0]["sha256"]
        == hashlib.sha256(b"download bytes").hexdigest()
    )
    assert "local_path" not in result.payload["downloads"][0]
    assert (
        proof_root / result.payload["downloads"][0]["path"]
    ).read_text() == "download bytes"
    assert score_proof_root(proof_root)["status"] == "passed"
    assert verify_proof_root(proof_root)["verified"] is True


@pytest.mark.asyncio
async def test_browser_downloads_filters_stale_profile_downloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    proof_root = tmp_path / "proof"
    download_file = tmp_path / "source-downloads" / "fixture-download.txt"
    stale_file = tmp_path / "source-downloads" / "old-download.txt"
    download_file.parent.mkdir()
    download_file.write_text("download bytes", encoding="utf-8")
    stale_file.write_text("old bytes", encoding="utf-8")
    _FakeRemoteEnvironment.download_path = download_file
    _FakeRemoteEnvironment.stale_download_path = stale_file
    _write_env_record(proof_root)
    browser_module.append_command(proof_root, command="env.open", status="passed")

    result = await browser_downloads(env_id="dev", proof_root=proof_root)

    assert result.status == "passed"
    assert result.payload["staleDownloadCount"] == 1
    assert "token=secret" not in result.payload["downloads"][0]["redactedUrl"]
    assert result.payload["downloads"][0]["redactedUrl"] == (
        "https://fixture.test/download"
    )
    assert [download["file_name"] for download in result.payload["downloads"]] == [
        "fixture-download.txt"
    ]
    assert (
        proof_root / result.payload["downloads"][0]["path"]
    ).read_text() == "download bytes"
    assert not any(
        path.name == "old-download.txt"
        for path in (proof_root / "downloads").glob("**/*")
    )


@pytest.mark.asyncio
async def test_env_open_and_close_write_cleanup_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(browser_module, "BrowserEnvironment", _FakeLocalEnvironment)
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    opened = await env_open(
        name="dev",
        kind="local",
        proof_root=tmp_path,
        extension_id="dev-extension",
    )
    closed = await env_close(env_id="dev", proof_root=tmp_path)

    assert opened.payload["environment"]["browserWindowId"] == "window-1"
    assert opened.payload["environment"]["extensionId"] == "dev-extension"
    assert _FakeLocalEnvironment.instances[0].kwargs["config"].extension_id == (
        "dev-extension"
    )
    assert closed.payload["environment"]["status"] == "closed"
    cleanup = json.loads((tmp_path / "cleanup" / "status.json").read_text())
    assert cleanup["status"] == "passed"
    assert (tmp_path / "browser" / "environments" / "dev-closed.json").exists()
    assert score_proof_root(tmp_path)["status"] == "passed"
    assert verify_proof_root(tmp_path)["verified"] is True


@pytest.mark.asyncio
async def test_env_open_can_adopt_existing_browser_window_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(browser_module, "BrowserEnvironment", _FakeLocalEnvironment)
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    opened = await env_open(
        name="dev",
        kind="local",
        proof_root=tmp_path,
        browser_window_id="window-adopted",
        base_url="https://api.test",
    )

    assert opened.payload["environment"]["browserWindowId"] == "window-adopted"
    assert opened.payload["environment"]["adoptedBrowserWindow"] is True
    assert opened.payload["environment"]["verifiedCurrentUrl"] == (
        "https://fixture.test/current"
    )
    assert _FakeLocalEnvironment.instances == []


@pytest.mark.asyncio
async def test_env_close_detaches_adopted_browser_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path, browser_window_id="window-adopted")
    env_path = tmp_path / "browser" / "environments" / "dev.json"
    record = json.loads(env_path.read_text(encoding="utf-8"))
    record["adoptedBrowserWindow"] = True
    env_path.write_text(json.dumps(record), encoding="utf-8")

    closed = await env_close(env_id="dev", proof_root=tmp_path)

    assert closed.status == "passed"
    assert closed.payload["environment"]["status"] == "detached"
    assert closed.payload["environment"]["closeBehavior"] == (
        "adopted_browser_not_closed"
    )
    assert "close" not in _FakeRemoteEnvironment.calls


def test_cli_browser_find_requires_proof_root() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["workbench", "browser", "find", "dev", "--snapshot-id", "snap"])

    assert exc_info.value.code == 2


def test_cli_json_mode_reports_runtime_errors_as_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "workbench",
            "browser",
            "snapshot",
            "missing",
            "--proof-root",
            str(tmp_path),
            "--json",
        ]
    )

    assert code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "failed"
    assert "Unknown browser environment" in payload["error"]
    assert captured.err == ""


def test_cli_json_mode_reports_snapshot_bound_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_env_record(tmp_path)

    code = main(
        [
            "workbench",
            "browser",
            "snapshot",
            "dev",
            "--proof-root",
            str(tmp_path),
            "--max-html-bytes",
            "2000000",
            "--json",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert "max_html_bytes" in payload["error"]


@pytest.mark.asyncio
async def test_browser_screenshot_accepts_data_url_without_padding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _FakeRemoteEnvironment.fail_screenshot = False
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path)

    result = await browser_screenshot(env_id="dev", proof_root=tmp_path)

    assert result.status == "passed"
    request = next(
        call
        for call in _FakeRemoteEnvironment.calls
        if isinstance(call, BrowserScreenshotRequest)
    )
    assert request.timeout_ms == browser_module.BROWSER_WORKBENCH_SCREENSHOT_TIMEOUT_MS
    screenshot_path = tmp_path / result.payload["path"]
    assert screenshot_path.read_bytes() == b"png-bytes"
    assert score_proof_root(tmp_path)["status"] == "passed"
    assert verify_proof_root(tmp_path)["verified"] is True


@pytest.mark.asyncio
async def test_browser_workbench_verify_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path)

    await browser_snapshot(env_id="dev", proof_root=tmp_path)

    verified = verify_proof_root(tmp_path)
    assert verified["verified"] is True

    no_write_verified = verify_proof_root(tmp_path, write=False)
    assert no_write_verified["status"] == "passed"
    assert no_write_verified["failures"] == []


@pytest.mark.asyncio
async def test_browser_action_without_post_snapshot_is_review_gated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path)
    snapshot = await browser_snapshot(env_id="dev", proof_root=tmp_path)

    result = await browser_nrd_action(
        env_id="dev",
        action="click",
        snapshot_id=snapshot.payload["snapshotId"],
        frame_id="main",
        data_nrd="main:submit",
        proof_root=tmp_path,
        post_snapshot=False,
    )

    assert result.status == "needs_review"
    assert "postSnapshotId" not in result.payload
    score = score_proof_root(tmp_path)
    assert score["status"] == "needs_review"
    assert any(
        warning.get("warning") == "browser_action_post_snapshot_missing"
        for warning in score["warnings"]
    )


@pytest.mark.asyncio
async def test_browser_screenshot_failure_is_recorded_without_fake_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _FakeRemoteEnvironment.fail_screenshot = True
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path)

    result = await browser_screenshot(env_id="dev", proof_root=tmp_path)

    assert result.status == "needs_review"
    assert result.payload["captureSupported"] is False
    assert not list((tmp_path / "browser").glob("screenshots/*.png"))
    score = score_proof_root(tmp_path)
    assert score["status"] == "needs_review"
    assert any(
        warning.get("command") == "browser.screenshot" for warning in score["warnings"]
    )
    verified = verify_proof_root(tmp_path)
    assert verified["verified"] is False
    assert verified["status"] == "needs_review"

    _FakeRemoteEnvironment.fail_screenshot = False


def test_browser_workbench_score_fails_command_artifact_hash_mismatch(
    tmp_path: Path,
) -> None:
    (tmp_path / "browser" / "snapshots" / "snap_1").mkdir(parents=True)
    artifact = tmp_path / "browser" / "snapshots" / "snap_1" / "summary.json"
    artifact.write_text("{}", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "proofRootKind": "browser-workbench",
                "runId": tmp_path.name,
                "status": "materialized",
                "commandLedgerHash": "placeholder",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "cleanup").mkdir()
    (tmp_path / "cleanup" / "status.json").write_text(
        json.dumps({"status": "passed"}), encoding="utf-8"
    )
    command = {
        "schemaVersion": 1,
        "commandId": "cmd_1",
        "runId": tmp_path.name,
        "command": "browser.snapshot",
        "status": "passed",
        "artifacts": [
            {
                "path": "browser/snapshots/snap_1/summary.json",
                "role": "browser-snapshot-summary",
                "sha256": "wrong",
            }
        ],
    }
    commands = tmp_path / "commands.jsonl"
    commands.write_text(json.dumps(command) + "\n", encoding="utf-8")
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["commandLedgerHash"] = hashlib.sha256(commands.read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    score = score_proof_root(tmp_path)

    assert score["status"] == "failed"
    assert any(
        failure["code"] == "command_artifact_hash_mismatch"
        for failure in score["failures"]
    )


@pytest.mark.asyncio
async def test_browser_workbench_open_cleanup_status_is_review_gated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(browser_module, "BrowserEnvironment", _FakeLocalEnvironment)

    await env_open(name="dev", kind="local", proof_root=tmp_path)

    score = score_proof_root(tmp_path)
    verified = verify_proof_root(tmp_path)

    assert score["status"] == "needs_review"
    assert verified["verified"] is False
    assert any(
        warning["code"] == "cleanup_status_not_terminal"
        for warning in score["warnings"]
    )


@pytest.mark.asyncio
async def test_browser_workbench_score_verify_do_not_amplify_warning_codes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(tmp_path, browser_window_id="window-adopted")
    env_path = tmp_path / "browser" / "environments" / "dev.json"
    record = json.loads(env_path.read_text(encoding="utf-8"))
    record["adoptedBrowserWindow"] = True
    env_path.write_text(json.dumps(record), encoding="utf-8")

    await env_close(env_id="dev", proof_root=tmp_path)
    browser_module.append_command(
        tmp_path,
        command="score",
        status="passed",
        warnings=["command_warning"],
    )
    browser_module._update_manifest_hash(
        tmp_path, "commandLedgerHash", tmp_path / "commands.jsonl"
    )

    score = score_proof_root(tmp_path)
    verified = verify_proof_root(tmp_path)

    assert score["status"] == "passed"
    assert verified["verified"] is True
    assert any(
        warning["command"] == "env.close"
        and warning["warning"] == "adopted_browser_not_closed"
        for warning in verified["warnings"]
    )
    assert not any(
        warning["command"] in {"score", "verify"}
        and warning["warning"] == "command_warning"
        for warning in verified["warnings"]
    )

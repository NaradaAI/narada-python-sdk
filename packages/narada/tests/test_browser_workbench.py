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
from narada.environment import SessionDownloadItem
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
    instances: list["_FakeRemoteEnvironment"] = []
    fail_screenshot: bool = False
    fail_close: bool = False
    download_path: Path | None = None
    stale_download_path: Path | None = None
    cloud_downloads: list[SessionDownloadItem] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.__class__.instances.append(self)

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
        if self.__class__.fail_close:
            raise RuntimeError(
                "stop failed with signed URL https://example.test/?X-Amz-Signature=secret"
            )

    async def get_downloaded_files(self) -> list[SessionDownloadItem]:
        self.__class__.calls.append("get_downloaded_files")
        return self.__class__.cloud_downloads


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


class _FakeCloudEnvironment:
    instances: list["_FakeCloudEnvironment"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.browser_window_id = "cloud-window-1"
        self._session_id = "cloud-session-1"
        self._config = kwargs["config"]
        self._initialization_url = (
            kwargs.get("dev_app_origin_override") or "https://dev-app.narada.ai"
        ) + "/initialize?customToken=test"
        self.stopped_playwright = False
        self.__class__.instances.append(self)

    @property
    def cloud_browser_session_id(self) -> str:
        return self._session_id

    async def start(self) -> None:
        return None

    async def _stop_playwright(self) -> None:
        self.stopped_playwright = True


@pytest.fixture(autouse=True)
def reset_fake_remote_environment() -> None:
    _FakeRemoteEnvironment.calls = []
    _FakeRemoteEnvironment.instances = []
    _FakeRemoteEnvironment.download_path = None
    _FakeRemoteEnvironment.stale_download_path = None
    _FakeRemoteEnvironment.cloud_downloads = []
    _FakeRemoteEnvironment.fail_close = False
    _FakeLocalEnvironment.instances = []
    _FakeCloudEnvironment.instances = []


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
async def test_browser_downloads_materializes_cloud_replay_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    async def fake_download_to_file(url: str, destination: Path) -> int:
        assert url == "https://signed.example/download.txt?X-Amz-Signature=secret"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"cloud download bytes")
        return len(b"cloud download bytes")

    monkeypatch.setattr(browser_module, "_download_to_file", fake_download_to_file)
    proof_root = tmp_path / "proof"
    _write_env_record(
        proof_root,
        env_id="cloud-dev",
        browser_window_id="cloud-window-1",
        extra={
            "kind": "cloud",
            "cloudBrowserSessionId": "cloud-session-1",
            "ownership": "sdk-created",
        },
    )
    _FakeRemoteEnvironment.cloud_downloads = [
        SessionDownloadItem(
            file_name="cloud-download.txt",
            size=20,
            download_url="https://signed.example/download.txt?X-Amz-Signature=secret",
            source_key="cloud-browser/session/download.txt",
        )
    ]

    result = await browser_downloads(env_id="cloud-dev", proof_root=proof_root)

    assert result.status == "passed"
    download = result.payload["downloads"][0]
    assert download["source"] == "cloud-browser-replay"
    assert download["sourceS3Key"] == "cloud-browser/session/download.txt"
    assert download["redactedDownloadUrl"] == "https://signed.example/download.txt"
    assert (proof_root / download["path"]).read_bytes() == b"cloud download bytes"
    assert download["sha256"] == hashlib.sha256(b"cloud download bytes").hexdigest()
    root_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in proof_root.rglob("*")
        if path.is_file() and path.suffix not in {".png"}
    )
    assert "X-Amz-Signature=secret" not in root_text
    assert score_proof_root(proof_root)["status"] == "passed"
    assert verify_proof_root(proof_root)["verified"] is True


@pytest.mark.asyncio
async def test_browser_downloads_cloud_without_materialized_bytes_needs_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    async def fake_download_to_file(url: str, destination: Path) -> int:
        del url
        del destination
        raise RuntimeError("signed URL expired")

    monkeypatch.setattr(browser_module, "_download_to_file", fake_download_to_file)
    proof_root = tmp_path / "proof"
    _write_env_record(
        proof_root,
        env_id="cloud-dev",
        browser_window_id="cloud-window-1",
        extra={
            "kind": "cloud",
            "cloudBrowserSessionId": "cloud-session-1",
            "ownership": "sdk-created",
        },
    )
    _FakeRemoteEnvironment.cloud_downloads = [
        SessionDownloadItem(
            file_name="cloud-download.txt",
            size=20,
            download_url="https://signed.example/download.txt?X-Amz-Signature=secret",
            source_key="cloud-browser/session/download.txt",
        )
    ]

    result = await browser_downloads(env_id="cloud-dev", proof_root=proof_root)

    assert result.status == "needs_review"
    assert result.payload["downloads"][0]["downloadStatus"] == "failed"
    assert "X-Amz-Signature=secret" not in json.dumps(result.payload)
    score = score_proof_root(proof_root)
    assert score["status"] == "needs_review"
    assert any(
        warning.get("command") == "browser.downloads"
        and warning.get("warning") == "cloud_download_fetch_failed"
        for warning in score["warnings"]
    )


@pytest.mark.asyncio
async def test_browser_downloads_cloud_partial_materialization_needs_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    async def fake_download_to_file(url: str, destination: Path) -> int:
        if "missing" in url:
            raise RuntimeError("signed URL expired")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"cloud download bytes")
        return len(b"cloud download bytes")

    monkeypatch.setattr(browser_module, "_download_to_file", fake_download_to_file)
    proof_root = tmp_path / "proof"
    _write_env_record(
        proof_root,
        env_id="cloud-dev",
        browser_window_id="cloud-window-1",
        extra={
            "kind": "cloud",
            "cloudBrowserSessionId": "cloud-session-1",
            "ownership": "sdk-created",
        },
    )
    _FakeRemoteEnvironment.cloud_downloads = [
        SessionDownloadItem(
            file_name="cloud-download.txt",
            size=20,
            download_url="https://signed.example/download.txt?X-Amz-Signature=secret",
            source_key="cloud-browser/session/download.txt",
        ),
        SessionDownloadItem(
            file_name="missing.txt",
            size=20,
            download_url="https://signed.example/missing.txt?X-Amz-Signature=secret",
            source_key="cloud-browser/session/missing.txt",
        ),
    ]

    result = await browser_downloads(env_id="cloud-dev", proof_root=proof_root)

    assert result.status == "needs_review"
    assert [row["downloadStatus"] for row in result.payload["downloads"]] == [
        "downloaded",
        "failed",
    ]
    score = score_proof_root(proof_root)
    assert score["status"] == "needs_review"


@pytest.mark.asyncio
async def test_browser_downloads_cloud_duplicate_names_do_not_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    async def fake_download_to_file(url: str, destination: Path) -> int:
        content = url.encode("utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return len(content)

    monkeypatch.setattr(browser_module, "_download_to_file", fake_download_to_file)
    proof_root = tmp_path / "proof"
    _write_env_record(
        proof_root,
        env_id="cloud-dev",
        browser_window_id="cloud-window-1",
        extra={
            "kind": "cloud",
            "cloudBrowserSessionId": "cloud-session-1",
            "ownership": "sdk-created",
        },
    )
    _FakeRemoteEnvironment.cloud_downloads = [
        SessionDownloadItem(
            file_name="duplicate.txt",
            size=20,
            download_url="https://signed.example/one.txt",
            source_key="cloud-browser/session/one.txt",
        ),
        SessionDownloadItem(
            file_name="duplicate.txt",
            size=20,
            download_url="https://signed.example/two.txt",
            source_key="cloud-browser/session/two.txt",
        ),
    ]

    result = await browser_downloads(env_id="cloud-dev", proof_root=proof_root)

    assert result.status == "passed"
    paths = [row["path"] for row in result.payload["downloads"]]
    assert paths[0].endswith("/000-duplicate.txt")
    assert paths[1].endswith("/001-duplicate.txt")
    assert paths[0] != paths[1]
    assert (proof_root / paths[0]).read_text(encoding="utf-8") == (
        "https://signed.example/one.txt"
    )
    assert (proof_root / paths[1]).read_text(encoding="utf-8") == (
        "https://signed.example/two.txt"
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
    monkeypatch.setattr(browser_module, "_local_process_is_running", lambda pid: False)
    monkeypatch.setattr(
        browser_module, "_tcp_port_is_listening", lambda port, host=None: False
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
    assert closed.payload["environment"]["localBrowserProcessStatus"] == (
        "already_exited"
    )
    assert closed.payload["environment"]["localBrowserCdpPortStatus"] == "closed"
    cleanup = json.loads((tmp_path / "cleanup" / "status.json").read_text())
    assert cleanup["status"] == "passed"
    assert cleanup["localBrowserProcessStatus"] == "already_exited"
    assert cleanup["localBrowserCdpPortStatus"] == "closed"
    assert (tmp_path / "browser" / "environments" / "dev-closed.json").exists()
    score = score_proof_root(tmp_path)
    assert score["status"] == "needs_review"
    assert any(
        warning["code"] == "browser_workbench_no_materialized_evidence"
        for warning in score["warnings"]
    )
    assert verify_proof_root(tmp_path)["verified"] is False


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
async def test_env_open_can_create_cloud_browser_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "CloudBrowserEnvironment", _FakeCloudEnvironment
    )

    opened = await env_open(
        name="cloud-dev",
        kind="cloud",
        proof_root=tmp_path,
        base_url="https://api.test/fast/v2",
        session_name="m5-cloud-test",
        session_timeout=900,
    )

    record = opened.payload["environment"]
    assert record["kind"] == "cloud"
    assert record["ownership"] == "sdk-created"
    assert record["browserWindowId"] == "cloud-window-1"
    assert record["cloudBrowserSessionId"] == "cloud-session-1"
    assert record["sessionName"] == "m5-cloud-test"
    assert record["sessionTimeout"] == 900
    assert _FakeCloudEnvironment.instances[0].kwargs["base_url"] == (
        "https://api.test/fast/v2"
    )
    assert record["initializationUrlOrigin"] == "https://dev-app.narada.ai"
    assert _FakeCloudEnvironment.instances[0].stopped_playwright is True
    lifecycle = (
        tmp_path / "browser" / "cloud-sessions" / "cloud-session-1" / "status.jsonl"
    )
    assert lifecycle.exists()
    assert (
        json.loads(lifecycle.read_text(encoding="utf-8").splitlines()[0])["ownership"]
        == "sdk-created"
    )
    score = score_proof_root(tmp_path)
    assert score["status"] == "needs_review"
    assert any(
        warning["code"] == "cleanup_status_not_terminal"
        for warning in score["warnings"]
    )


@pytest.mark.asyncio
async def test_cloud_env_open_then_close_keeps_lifecycle_artifacts_immutable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "CloudBrowserEnvironment", _FakeCloudEnvironment
    )
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    await env_open(name="cloud-dev", kind="cloud", proof_root=tmp_path)
    await env_close(env_id="cloud-dev", proof_root=tmp_path)

    lifecycle = (
        tmp_path / "browser" / "cloud-sessions" / "cloud-session-1" / "status.jsonl"
    )
    event_files = sorted(
        (tmp_path / "browser" / "cloud-sessions" / "cloud-session-1" / "events").glob(
            "*.json"
        )
    )
    assert [
        json.loads(line)["event"] for line in lifecycle.read_text().splitlines()
    ] == [
        "env.open",
        "env.close",
    ]
    assert len(event_files) == 2
    score = score_proof_root(tmp_path)
    assert score["status"] == "needs_review"
    assert any(
        warning["code"] == "browser_workbench_no_materialized_evidence"
        for warning in score["warnings"]
    )
    assert verify_proof_root(tmp_path)["verified"] is False


@pytest.mark.asyncio
async def test_env_open_cloud_forwards_dev_branch_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "CloudBrowserEnvironment", _FakeCloudEnvironment
    )

    opened = await env_open(
        name="cloud-dev",
        kind="cloud",
        proof_root=tmp_path,
        base_url="https://api.test/fast/v2",
        dev_app_origin_override="https://branch.example.test",
        dev_extension_s3_bucket="narada-chrome-extension-test-builds",
        dev_extension_s3_key="proof/m5-extension.zip",
    )

    record = opened.payload["environment"]
    instance = _FakeCloudEnvironment.instances[0]
    assert instance.kwargs["dev_app_origin_override"] == "https://branch.example.test"
    assert (
        instance.kwargs["dev_extension_s3_bucket"]
        == "narada-chrome-extension-test-builds"
    )
    assert instance.kwargs["dev_extension_s3_key"] == "proof/m5-extension.zip"
    assert record["initializationUrlOrigin"] == "https://branch.example.test"
    assert record["devAppOriginOverride"] == "https://branch.example.test"
    assert record["devExtensionS3Bucket"] == "narada-chrome-extension-test-builds"
    assert record["devExtensionS3Key"] == "proof/m5-extension.zip"


@pytest.mark.asyncio
async def test_env_open_dev_cloud_overrides_require_cloud_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dev overrides require --kind cloud"):
        await env_open(
            name="dev",
            kind="local",
            proof_root=tmp_path,
            dev_app_origin_override="https://branch.example.test",
        )


@pytest.mark.asyncio
async def test_env_open_dev_extension_override_requires_bucket_and_key(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must be provided together"):
        await env_open(
            name="cloud-dev",
            kind="cloud",
            proof_root=tmp_path,
            dev_extension_s3_bucket="narada-chrome-extension-test-builds",
        )


@pytest.mark.asyncio
async def test_env_open_can_adopt_cloud_browser_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    opened = await env_open(
        name="cloud-dev",
        kind="cloud",
        proof_root=tmp_path,
        browser_window_id="cloud-window-adopted",
        cloud_browser_session_id="cloud-session-adopted",
        base_url="https://api.test/fast/v2",
    )

    record = opened.payload["environment"]
    assert record["kind"] == "cloud"
    assert record["ownership"] == "adopted"
    assert record["browserWindowId"] == "cloud-window-adopted"
    assert record["cloudBrowserSessionId"] == "cloud-session-adopted"
    assert _FakeRemoteEnvironment.instances[0].kwargs["cloud_browser_session_id"] == (
        "cloud-session-adopted"
    )


@pytest.mark.asyncio
async def test_env_open_cloud_adoption_requires_session_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cloud adoption requires"):
        await env_open(
            name="cloud-dev",
            kind="cloud",
            proof_root=tmp_path,
            browser_window_id="cloud-window-adopted",
        )


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


@pytest.mark.asyncio
async def test_env_close_terminates_sdk_created_local_browser_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    monkeypatch.setattr(browser_module, "_local_process_is_running", lambda pid: True)
    monkeypatch.setattr(
        browser_module,
        "_local_process_identity_status",
        lambda pid, record: {"status": "verified", "pid": pid},
    )
    port_checks: list[tuple[int, str | None]] = []

    def fake_port_probe(port: int, host: str | None = None) -> bool:
        port_checks.append((port, host))
        return False

    monkeypatch.setattr(browser_module, "_tcp_port_is_listening", fake_port_probe)
    terminated: list[int] = []

    async def fake_terminate(pid: int) -> dict[str, Any]:
        terminated.append(pid)
        return {"status": "terminated", "pid": pid}

    monkeypatch.setattr(browser_module, "_terminate_local_process", fake_terminate)
    _write_env_record(
        tmp_path,
        extra={
            "kind": "local",
            "ownership": "sdk-created",
            "attachToExisting": False,
            "browserProcessId": 123,
            "cdpHost": "127.0.0.42",
            "cdpPort": 9333,
            "userDataDir": "/tmp/narada-browser-dev",
        },
    )

    closed = await env_close(env_id="dev", proof_root=tmp_path)

    assert closed.status == "passed"
    assert "close" in _FakeRemoteEnvironment.calls
    assert terminated == [123]
    assert closed.payload["environment"]["localBrowserProcessStatus"] == "terminated"
    assert closed.payload["environment"]["localBrowserCdpPortStatus"] == "closed"
    assert port_checks == [(9333, "127.0.0.42")]
    command_row = json.loads(
        (tmp_path / "commands.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert (
        "local_browser_process_terminated_after_remote_close" in command_row["warnings"]
    )
    cleanup = json.loads((tmp_path / "cleanup" / "status.json").read_text())
    assert cleanup["status"] == "passed"
    assert cleanup["localBrowserProcessStatus"] == "terminated"
    assert cleanup["localBrowserCdpPortStatus"] == "closed"


@pytest.mark.asyncio
async def test_env_close_refuses_to_kill_local_browser_when_identity_mismatches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    monkeypatch.setattr(browser_module, "_local_process_is_running", lambda pid: True)
    monkeypatch.setattr(
        browser_module,
        "_local_process_identity_status",
        lambda pid, record: {"status": "identity_mismatch", "pid": pid},
    )
    monkeypatch.setattr(
        browser_module, "_tcp_port_is_listening", lambda port, host=None: False
    )
    terminated: list[int] = []

    async def fake_terminate(pid: int) -> dict[str, Any]:
        terminated.append(pid)
        return {"status": "terminated", "pid": pid}

    monkeypatch.setattr(browser_module, "_terminate_local_process", fake_terminate)
    _write_env_record(
        tmp_path,
        extra={
            "kind": "local",
            "ownership": "sdk-created",
            "attachToExisting": False,
            "browserProcessId": 123,
            "cdpHost": "127.0.0.1",
            "cdpPort": 9333,
            "userDataDir": "/tmp/narada-browser-dev",
        },
    )

    closed = await env_close(env_id="dev", proof_root=tmp_path)

    assert closed.status == "failed"
    assert terminated == []
    assert closed.payload["environment"]["status"] == "close_failed"
    assert closed.payload["environment"]["localBrowserProcessStatus"] == (
        "identity_mismatch"
    )
    assert closed.payload["environment"]["localBrowserProcessIdentity"] == {
        "status": "identity_mismatch",
        "pid": 123,
    }
    command_row = json.loads(
        (tmp_path / "commands.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert "browser_environment_process_cleanup_failed" in command_row["warnings"]
    cleanup = json.loads((tmp_path / "cleanup" / "status.json").read_text())
    assert cleanup["status"] == "failed"
    assert cleanup["localBrowserProcessStatus"] == "identity_mismatch"


def test_local_process_identity_requires_exact_debug_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        browser_module,
        "_process_command_line",
        lambda pid: (
            "/Applications/Chrome --remote-debugging-port=93330 "
            "--user-data-dir=/tmp/narada-browser-dev"
        ),
    )

    status = browser_module._local_process_identity_status(
        123,
        {"cdpPort": 9333, "userDataDir": "/tmp/narada-browser-dev"},
    )

    assert status["status"] == "identity_mismatch"
    assert "--remote-debugging-port=9333" in status["missingMarkers"]


def test_local_process_identity_requires_exact_user_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        browser_module,
        "_process_command_line",
        lambda pid: (
            "/Applications/Chrome --remote-debugging-port=9333 "
            "--user-data-dir=/tmp/narada-browser-dev-old"
        ),
    )

    status = browser_module._local_process_identity_status(
        123,
        {"cdpPort": 9333, "userDataDir": "/tmp/narada-browser-dev"},
    )

    assert status["status"] == "identity_mismatch"
    assert "--user-data-dir=/tmp/narada-browser-dev" in status["missingMarkers"]


def test_local_process_identity_accepts_exact_launch_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        browser_module,
        "_process_command_line",
        lambda pid: (
            "/Applications/Chrome --remote-debugging-port=9333 "
            "--user-data-dir=/tmp/narada-browser-dev --new-window"
        ),
    )

    status = browser_module._local_process_identity_status(
        123,
        {"cdpPort": 9333, "userDataDir": "/tmp/narada-browser-dev"},
    )

    assert status == {"status": "verified", "pid": 123}


@pytest.mark.asyncio
async def test_env_close_fails_if_sdk_created_local_cdp_port_stays_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    monkeypatch.setattr(browser_module, "_local_process_is_running", lambda pid: False)
    monkeypatch.setattr(
        browser_module, "_tcp_port_is_listening", lambda port, host=None: True
    )
    _write_env_record(
        tmp_path,
        extra={
            "kind": "local",
            "ownership": "sdk-created",
            "attachToExisting": False,
            "browserProcessId": 123,
            "cdpPort": 9333,
        },
    )

    closed = await env_close(env_id="dev", proof_root=tmp_path)

    assert closed.status == "failed"
    assert closed.payload["environment"]["status"] == "close_failed"
    assert closed.payload["environment"]["closeBehavior"] == "process_cleanup_failed"
    assert closed.payload["environment"]["localBrowserProcessStatus"] == (
        "already_exited"
    )
    assert closed.payload["environment"]["localBrowserCdpPortStatus"] == "listening"
    cleanup = json.loads((tmp_path / "cleanup" / "status.json").read_text())
    assert cleanup["status"] == "failed"
    assert cleanup["localBrowserCdpPortStatus"] == "listening"
    score = score_proof_root(tmp_path)
    assert score["status"] == "tainted"
    assert any(taint["code"] == "cleanup_failed" for taint in score["taints"])


@pytest.mark.asyncio
async def test_env_close_stops_sdk_created_cloud_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(
        tmp_path,
        env_id="cloud-dev",
        browser_window_id="cloud-window-1",
        extra={
            "kind": "cloud",
            "cloudBrowserSessionId": "cloud-session-1",
            "ownership": "sdk-created",
        },
    )

    closed = await env_close(env_id="cloud-dev", proof_root=tmp_path)

    assert closed.status == "passed"
    assert closed.payload["environment"]["status"] == "closed"
    assert "close" in _FakeRemoteEnvironment.calls
    cleanup = json.loads((tmp_path / "cleanup" / "status.json").read_text())
    assert cleanup["cloudBrowserSessionId"] == "cloud-session-1"
    assert cleanup["cloudBrowserOwnership"] == "sdk-created"
    lifecycle = (
        tmp_path / "browser" / "cloud-sessions" / "cloud-session-1" / "status.jsonl"
    )
    assert any(
        json.loads(line)["status"] == "closed"
        for line in lifecycle.read_text(encoding="utf-8").splitlines()
    )
    score = score_proof_root(tmp_path)
    assert score["status"] == "needs_review"
    assert any(
        warning["code"] == "browser_workbench_no_materialized_evidence"
        for warning in score["warnings"]
    )
    assert verify_proof_root(tmp_path)["verified"] is False


@pytest.mark.asyncio
async def test_env_close_failure_records_failed_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _FakeRemoteEnvironment.fail_close = True
    _write_env_record(
        tmp_path,
        env_id="cloud-dev",
        browser_window_id="cloud-window-1",
        extra={
            "kind": "cloud",
            "cloudBrowserSessionId": "cloud-session-1",
            "ownership": "sdk-created",
        },
    )

    closed = await env_close(env_id="cloud-dev", proof_root=tmp_path)

    assert closed.status == "failed"
    assert closed.payload["environment"]["status"] == "close_failed"
    cleanup = json.loads((tmp_path / "cleanup" / "status.json").read_text())
    assert cleanup["status"] == "failed"
    assert "X-Amz-Signature=secret" not in cleanup["error"]
    score = score_proof_root(tmp_path)
    assert score["status"] == "tainted"
    assert any(taint["code"] == "cleanup_failed" for taint in score["taints"])


@pytest.mark.asyncio
async def test_env_close_detaches_adopted_cloud_session_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )
    _write_env_record(
        tmp_path,
        env_id="cloud-dev",
        browser_window_id="cloud-window-adopted",
        extra={
            "kind": "cloud",
            "cloudBrowserSessionId": "cloud-session-adopted",
            "ownership": "adopted",
            "adoptedBrowserWindow": True,
        },
    )

    closed = await env_close(env_id="cloud-dev", proof_root=tmp_path)

    assert closed.status == "passed"
    assert closed.payload["environment"]["status"] == "detached"
    assert "close" not in _FakeRemoteEnvironment.calls
    command_rows = [
        json.loads(line)
        for line in (tmp_path / "commands.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(
        row.get("command") == "env.close"
        and "adopted_cloud_browser_not_stopped" in row.get("warnings", [])
        for row in command_rows
    )
    score = score_proof_root(tmp_path)
    assert score["status"] == "needs_review"
    assert any(
        warning["code"] == "browser_workbench_no_materialized_evidence"
        for warning in score["warnings"]
    )


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
async def test_browser_workbench_metadata_only_root_cannot_verify_clean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(browser_module, "BrowserEnvironment", _FakeLocalEnvironment)
    monkeypatch.setattr(
        browser_module, "RemoteBrowserEnvironment", _FakeRemoteEnvironment
    )

    await env_open(name="dev", kind="local", proof_root=tmp_path)
    await env_close(env_id="dev", proof_root=tmp_path)

    score = score_proof_root(tmp_path)
    verified = verify_proof_root(tmp_path)

    assert score["status"] == "needs_review"
    assert verified["verified"] is False
    assert any(
        warning["code"] == "browser_workbench_no_materialized_evidence"
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

    await browser_snapshot(env_id="dev", proof_root=tmp_path)
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

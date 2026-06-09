from __future__ import annotations

import base64
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from narada_core.actions.models import (
    BrowserActionResponse,
    BrowserClickNrdRequest,
    BrowserDownloadsRequest,
    BrowserDownloadsResponse,
    BrowserElementHandle,
    BrowserFillNrdRequest,
    BrowserPageSnapshotRequest,
    BrowserPageSnapshotResponse,
    BrowserScreenshotRequest,
    BrowserScreenshotResponse,
    BrowserSelectNrdRequest,
    GetUrlRequest,
    GetUrlResponse,
    GoToUrlRequest,
)

from narada.config import BrowserConfig
from narada.environment import BrowserEnvironment, RemoteBrowserEnvironment
from narada.workbench import (
    _default_out_dir,
    _redact_sensitive_text,
    _redact_url,
    _sha256_file,
    _update_manifest_hash,
    _write_json,
    _write_redaction_report,
    append_command,
    default_api_base_url,
    default_auth_headers,
)

BROWSER_WORKBENCH_SCREENSHOT_TIMEOUT_MS = 45_000


@dataclass(frozen=True)
class BrowserWorkbenchCommandResult:
    status: str
    payload: dict[str, Any]
    command_id: str
    proof_root: Path


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned[:80] or "browser"


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _proof_root_started_after(root: Path) -> str | None:
    commands_path = root / "commands.jsonl"
    if not commands_path.exists():
        return None
    for line in commands_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        started_at = row.get("startedAt")
        if isinstance(started_at, str) and _parse_iso_datetime(started_at):
            return started_at
    return None


def _download_is_in_scope(download: dict[str, Any], started_after: str | None) -> bool:
    lower_bound = _parse_iso_datetime(started_after)
    if lower_bound is None:
        return True
    start_time = _parse_iso_datetime(
        download.get("start_time") or download.get("startTime")
    )
    end_time = _parse_iso_datetime(download.get("end_time") or download.get("endTime"))
    observed_time = start_time or end_time
    if observed_time is None:
        return True
    return observed_time >= lower_bound


def _origin(value: str) -> str:
    split = urlsplit(value)
    return urlunsplit((split.scheme, split.netloc, "", "", ""))


def _browser_root(proof_root: str | Path | None, label: str) -> Path:
    root = Path(proof_root) if proof_root is not None else _default_out_dir(label)
    preexisting_root = root.exists() and any(root.iterdir())
    root.mkdir(parents=True, exist_ok=True)
    (root / "browser").mkdir(parents=True, exist_ok=True)
    (root / "cleanup").mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        _write_json(
            manifest_path,
            {
                "schemaVersion": 1,
                "proofRootKind": "browser-workbench",
                "runId": root.name,
                "label": label,
                "status": "materialized",
                "sensitiveArtifacts": True,
                "taints": ["proof_root_preexisting"] if preexisting_root else [],
                "failures": [],
            },
        )
    cleanup_path = root / "cleanup" / "status.json"
    if not cleanup_path.exists():
        _write_json(
            cleanup_path,
            {"status": "open", "reason": "browser workbench environment may be active"},
        )
    _write_redaction_report(root)
    return root


def _add_manifest_taint(root: Path, taint: str) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        return
    taints = manifest.setdefault("taints", [])
    if isinstance(taints, list) and taint not in taints:
        taints.append(taint)
    _write_json(manifest_path, manifest)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _artifact(
    root: Path, path: Path, role: str, *, sensitive: bool = True
) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "sha256": _sha256_file(path),
        "sensitive": sensitive,
    }


def _append_artifacts(root: Path, artifacts: list[dict[str, Any]]) -> None:
    artifact_index = root / "browser" / "artifacts.jsonl"
    for artifact in artifacts:
        _append_jsonl(artifact_index, artifact)


def _finish_command(
    root: Path,
    *,
    command: str,
    status: str,
    payload: dict[str, Any],
    command_id: str | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    taints: list[str] | None = None,
    ids: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> BrowserWorkbenchCommandResult:
    artifact_rows = artifacts or []
    if artifact_rows:
        _append_artifacts(root, artifact_rows)
    row = append_command(
        root,
        command=command,
        status=status,
        command_id=command_id,
        artifacts=artifact_rows,
        warnings=warnings,
        taints=taints,
        ids=ids,
        inputs=inputs,
    )
    _write_redaction_report(root)
    _update_manifest_hash(root, "commandLedgerHash", root / "commands.jsonl")
    artifact_index = root / "browser" / "artifacts.jsonl"
    if artifact_index.exists():
        _update_manifest_hash(root, "browserArtifactIndexHash", artifact_index)
    return BrowserWorkbenchCommandResult(
        status=status,
        payload={
            **payload,
            "schemaVersion": 1,
            "status": status,
            "proofRoot": str(root),
        },
        command_id=row["commandId"],
        proof_root=root,
    )


def _env_path(root: Path, env_id: str) -> Path:
    return root / "browser" / "environments" / f"{_safe_slug(env_id)}.json"


def _load_env(root: Path, env_id: str) -> dict[str, Any]:
    path = _env_path(root, env_id)
    if not path.exists():
        raise ValueError(f"Unknown browser environment {env_id!r} in {root}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Browser environment record {path} is not an object")
    return loaded


def _remote_env(
    record: dict[str, Any], *, base_url: str | None
) -> RemoteBrowserEnvironment:
    browser_window_id = record.get("browserWindowId")
    if not isinstance(browser_window_id, str) or not browser_window_id:
        raise ValueError("Browser environment record has no browserWindowId")
    return RemoteBrowserEnvironment(
        browser_window_id=browser_window_id,
        auth_headers=default_auth_headers(),
        base_url=base_url or record.get("apiBaseUrl") or default_api_base_url(),
    )


def _write_env(root: Path, env_id: str, record: dict[str, Any]) -> dict[str, Any]:
    path = _env_path(root, env_id)
    _write_json(path, record)
    return _artifact(root, path, "browser-environment", sensitive=False)


def _write_env_lifecycle_snapshot(
    root: Path, env_id: str, status: str, record: dict[str, Any]
) -> dict[str, Any]:
    path = root / "browser" / "environments" / f"{_safe_slug(env_id)}-{status}.json"
    _write_json(path, record)
    return _artifact(root, path, "browser-environment", sensitive=False)


def _snapshot_dir(root: Path, snapshot_id: str) -> Path:
    return root / "browser" / "snapshots" / _safe_slug(snapshot_id)


def _write_snapshot(
    root: Path, snapshot: BrowserPageSnapshotResponse
) -> list[dict[str, Any]]:
    snapshot_id = snapshot.snapshot_id
    directory = _snapshot_dir(root, snapshot_id)
    summary = snapshot.model_dump(
        exclude={"html", "visible_text", "elements", "frames"}
    )
    summary["paths"] = {
        "html": f"browser/snapshots/{_safe_slug(snapshot_id)}/simplified.html",
        "visibleText": f"browser/snapshots/{_safe_slug(snapshot_id)}/visible-text.txt",
        "elements": f"browser/snapshots/{_safe_slug(snapshot_id)}/elements.json",
        "frames": f"browser/snapshots/{_safe_slug(snapshot_id)}/frames.json",
    }
    summary_path = directory / "summary.json"
    html_path = directory / "simplified.html"
    text_path = directory / "visible-text.txt"
    elements_path = directory / "elements.json"
    frames_path = directory / "frames.json"
    _write_json(summary_path, summary)
    html_path.write_text(snapshot.html, encoding="utf-8")
    text_path.write_text(snapshot.visible_text or "", encoding="utf-8")
    _write_json(elements_path, snapshot.elements)
    _write_json(frames_path, snapshot.frames)
    _append_jsonl(
        root / "browser" / "page-snapshots.jsonl",
        {
            "snapshotId": snapshot_id,
            "url": snapshot.url,
            "title": snapshot.title,
            "htmlTruncated": snapshot.html_truncated,
            "visibleTextTruncated": snapshot.visible_text_truncated,
            "summaryPath": summary_path.relative_to(root).as_posix(),
        },
    )
    return [
        _artifact(root, summary_path, "browser-snapshot-summary", sensitive=False),
        _artifact(root, html_path, "browser-snapshot-html"),
        _artifact(root, text_path, "browser-snapshot-visible-text"),
        _artifact(root, elements_path, "browser-snapshot-elements"),
        _artifact(root, frames_path, "browser-snapshot-frames"),
    ]


def _load_snapshot_summary(root: Path, snapshot_id: str) -> dict[str, Any]:
    path = _snapshot_dir(root, snapshot_id) / "summary.json"
    if not path.exists():
        raise ValueError(f"Unknown browser snapshot {snapshot_id!r}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Browser snapshot summary {path} is not an object")
    return loaded


def _load_snapshot_elements(root: Path, snapshot_id: str) -> list[dict[str, Any]]:
    path = _snapshot_dir(root, snapshot_id) / "elements.json"
    if not path.exists():
        raise ValueError(f"Browser snapshot {snapshot_id!r} has no elements.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError(f"Browser snapshot elements {path} is not a list")
    return [item for item in loaded if isinstance(item, dict)]


def _element_for_handle(
    root: Path,
    *,
    snapshot_id: str,
    frame_id: str,
    data_nrd: str,
) -> dict[str, Any]:
    for element in _load_snapshot_elements(root, snapshot_id):
        if element.get("data_nrd") == data_nrd and element.get("frame_id") == frame_id:
            return element
    raise ValueError(
        f"No element with data-nrd {data_nrd!r} and frame {frame_id!r} in snapshot {snapshot_id!r}"
    )


def _handle(
    root: Path, snapshot_id: str, frame_id: str, data_nrd: str
) -> BrowserElementHandle:
    summary = _load_snapshot_summary(root, snapshot_id)
    element = _element_for_handle(
        root, snapshot_id=snapshot_id, frame_id=frame_id, data_nrd=data_nrd
    )
    fingerprint = element.get("fingerprint")
    return BrowserElementHandle(
        snapshot_id=snapshot_id,
        frame_id=frame_id,
        data_nrd=data_nrd,
        snapshot_url=str(summary.get("url") or ""),
        element_fingerprint=fingerprint if isinstance(fingerprint, str) else None,
    )


def _selectors_for_element(element: dict[str, Any]) -> dict[str, Any]:
    candidates: dict[str, Any] = {"naradaId": element.get("data_nrd")}
    tag_name = element.get("tag_name")
    text = element.get("text")
    if isinstance(tag_name, str) and tag_name:
        candidates["tagName"] = {"value": tag_name}
    if isinstance(text, str) and text:
        candidates["textContent"] = {"value": text[:200]}
    for key, selector_name in (
        ("aria_label", "ariaLabel"),
        ("placeholder", "placeholder"),
        ("href", "href"),
    ):
        value = element.get(key)
        if isinstance(value, str) and value:
            candidates[selector_name] = {"value": value}
    return candidates


def _line_set(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if line.strip()}


def _diff_visible_text(root: Path, before: str, after: str) -> dict[str, list[str]]:
    before_text = (_snapshot_dir(root, before) / "visible-text.txt").read_text(
        encoding="utf-8"
    )
    after_text = (_snapshot_dir(root, after) / "visible-text.txt").read_text(
        encoding="utf-8"
    )
    before_lines = _line_set(before_text)
    after_lines = _line_set(after_text)
    return {
        "added_text": sorted(after_lines - before_lines)[:100],
        "removed_text": sorted(before_lines - after_lines)[:100],
    }


def _decode_base64_content(value: str) -> bytes:
    content = value.strip()
    if content.lower().startswith("data:") and "," in content:
        content = content.split(",", 1)[1]
    content = re.sub(r"\s+", "", content)
    padding = (-len(content)) % 4
    if padding:
        content += "=" * padding
    return base64.b64decode(content, validate=False)


async def env_open(
    *,
    name: str,
    kind: str,
    proof_root: str | Path | None,
    base_url: str | None = None,
    initialization_url: str | None = None,
    cdp_port: int | None = None,
    extension_id: str | None = None,
    user_data_dir: str | None = None,
    profile_directory: str | None = None,
    attach_to_existing: bool = False,
    browser_window_id: str | None = None,
) -> BrowserWorkbenchCommandResult:
    if kind != "local":
        raise ValueError("M4 supports only --kind local")
    root = _browser_root(proof_root, f"browser-env-{name}")
    if (root / "commands.jsonl").exists():
        _add_manifest_taint(root, "proof_root_preexisting")
    api_base_url = base_url or default_api_base_url()
    if browser_window_id is not None:
        remote = RemoteBrowserEnvironment(
            browser_window_id=browser_window_id,
            auth_headers=default_auth_headers(),
            base_url=api_base_url,
        )
        current_url = (
            await remote._run_extension_action(GetUrlRequest(), GetUrlResponse)
        ).url
        record = {
            "schemaVersion": 1,
            "id": name,
            "kind": kind,
            "status": "open",
            "browserWindowId": browser_window_id,
            "browserProcessId": None,
            "apiBaseUrl": api_base_url,
            "apiBaseUrlOrigin": _origin(api_base_url),
            "initializationUrlOrigin": _origin(initialization_url)
            if initialization_url
            else None,
            "cdpPort": cdp_port,
            "extensionId": extension_id,
            "attachToExisting": True,
            "adoptedBrowserWindow": True,
            "verifiedCurrentUrl": current_url,
        }
        artifact = _write_env(root, name, record)
        return _finish_command(
            root,
            command="env.open",
            status="passed",
            payload={"environment": record},
            artifacts=[artifact],
            ids={"envId": name, "browserWindowId": browser_window_id},
            inputs={"kind": kind, "apiBaseUrlOrigin": record["apiBaseUrlOrigin"]},
        )

    config = BrowserConfig(
        initialization_url=initialization_url or BrowserConfig().initialization_url,
        cdp_port=cdp_port or BrowserConfig().cdp_port,
        extension_id=extension_id or BrowserConfig().extension_id,
        user_data_dir=user_data_dir or BrowserConfig().user_data_dir,
        profile_directory=profile_directory or BrowserConfig().profile_directory,
        interactive=False,
    )
    env = BrowserEnvironment(
        auth_headers=default_auth_headers(),
        base_url=api_base_url,
        config=config,
        attach_to_existing=attach_to_existing,
    )
    await env.start()
    record = {
        "schemaVersion": 1,
        "id": name,
        "kind": kind,
        "status": "open",
        "browserWindowId": env.browser_window_id,
        "browserProcessId": env.browser_process_id,
        "apiBaseUrl": api_base_url,
        "apiBaseUrlOrigin": _origin(api_base_url),
        "initializationUrlOrigin": _origin(config.initialization_url),
        "cdpPort": config.cdp_port,
        "extensionId": config.extension_id,
        "attachToExisting": attach_to_existing,
    }
    artifact = _write_env(root, name, record)
    await env._stop_playwright()
    return _finish_command(
        root,
        command="env.open",
        status="passed",
        payload={"environment": record},
        artifacts=[artifact],
        ids={"envId": name, "browserWindowId": env.browser_window_id},
        inputs={"kind": kind, "apiBaseUrlOrigin": record["apiBaseUrlOrigin"]},
    )


async def env_status(
    *,
    env_id: str,
    proof_root: str | Path,
    base_url: str | None = None,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-env-{env_id}")
    record = _load_env(root, env_id)
    env = _remote_env(record, base_url=base_url)
    warnings: list[str] = []
    url: str | None = None
    try:
        response = await env._run_extension_action(GetUrlRequest(), GetUrlResponse)
        url = response.url
    except Exception as exc:
        warnings.append(_redact_sensitive_text(str(exc)))
    payload = {"environment": record, "currentUrl": url}
    return _finish_command(
        root,
        command="env.status",
        status="passed" if url is not None else "needs_review",
        payload=payload,
        warnings=warnings,
        ids={"envId": env_id, "browserWindowId": record.get("browserWindowId")},
    )


async def env_close(
    *,
    env_id: str,
    proof_root: str | Path,
    base_url: str | None = None,
    close_adopted: bool = False,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-env-{env_id}")
    record = _load_env(root, env_id)
    is_adopted = record.get("adoptedBrowserWindow") is True
    warnings: list[str] = []
    if is_adopted and not close_adopted:
        record = {
            **record,
            "status": "detached",
            "closeBehavior": "adopted_browser_not_closed",
        }
        warnings.append("adopted_browser_not_closed")
    else:
        env = _remote_env(record, base_url=base_url)
        await env.close(timeout=30)
        record = {**record, "status": "closed", "closeBehavior": "closed"}
    artifact = _write_env_lifecycle_snapshot(
        root, env_id, str(record["status"]), record
    )
    _write_json(
        root / "cleanup" / "status.json",
        {"status": "passed", "browserEnvironmentStatus": record["status"]},
    )
    return _finish_command(
        root,
        command="env.close",
        status="passed",
        payload={"environment": record},
        artifacts=[artifact],
        warnings=warnings,
        ids={"envId": env_id, "browserWindowId": record.get("browserWindowId")},
    )


async def browser_goto(
    *,
    env_id: str,
    url: str,
    proof_root: str | Path,
    base_url: str | None = None,
    new_tab: bool = False,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-{env_id}")
    record = _load_env(root, env_id)
    env = _remote_env(record, base_url=base_url)
    await env._run_extension_action(
        GoToUrlRequest(url=url, new_tab=new_tab), timeout=60
    )
    action_row = {
        "type": "goto",
        "envId": env_id,
        "url": url,
        "newTab": new_tab,
    }
    _append_jsonl(root / "browser" / "actions.jsonl", action_row)
    return _finish_command(
        root,
        command="browser.goto",
        status="passed",
        payload=action_row,
        ids={"envId": env_id, "browserWindowId": record.get("browserWindowId")},
        inputs={"url": url},
    )


async def browser_snapshot(
    *,
    env_id: str,
    proof_root: str | Path,
    base_url: str | None = None,
    max_html_bytes: int = 500_000,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-{env_id}")
    record = _load_env(root, env_id)
    env = _remote_env(record, base_url=base_url)
    snapshot_id = f"snap_{uuid.uuid4().hex}"
    snapshot = await env._run_extension_action(
        BrowserPageSnapshotRequest(
            snapshot_id=snapshot_id,
            max_html_bytes=max_html_bytes,
            include_visible_text=True,
        ),
        BrowserPageSnapshotResponse,
        timeout=60,
    )
    artifacts = _write_snapshot(root, snapshot)
    warnings = ["html_truncated"] if snapshot.html_truncated else []
    return _finish_command(
        root,
        command="browser.snapshot",
        status="needs_review" if warnings else "passed",
        payload={
            "snapshotId": snapshot.snapshot_id,
            "url": snapshot.url,
            "title": snapshot.title,
            "htmlTruncated": snapshot.html_truncated,
            "elementCount": len(snapshot.elements),
        },
        artifacts=artifacts,
        warnings=warnings,
        ids={"envId": env_id, "snapshotId": snapshot.snapshot_id},
    )


async def browser_find(
    *,
    env_id: str,
    snapshot_id: str,
    proof_root: str | Path,
    text: str | None = None,
    tag_name: str | None = None,
    data_nrd: str | None = None,
    interactive_only: bool = False,
    limit: int = 20,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-{env_id}")
    matches: list[dict[str, Any]] = []
    needle = text.lower() if text is not None else None
    tag = tag_name.lower() if tag_name is not None else None
    for element in _load_snapshot_elements(root, snapshot_id):
        if data_nrd is not None and element.get("data_nrd") != data_nrd:
            continue
        if tag is not None and str(element.get("tag_name") or "").lower() != tag:
            continue
        if interactive_only and element.get("interactive") is not True:
            continue
        if needle is not None:
            haystack = " ".join(
                str(element.get(key) or "")
                for key in ("text", "aria_label", "placeholder", "href")
            ).lower()
            if needle not in haystack:
                continue
        matches.append(element)
        if len(matches) >= limit:
            break
    row = {"envId": env_id, "snapshotId": snapshot_id, "matches": matches}
    _append_jsonl(root / "browser" / "findings.jsonl", row)
    return _finish_command(
        root,
        command="browser.find",
        status="passed",
        payload={"matches": matches, "matchCount": len(matches)},
        ids={"envId": env_id, "snapshotId": snapshot_id},
        inputs={
            "text": text,
            "tagName": tag_name,
            "dataNrd": data_nrd,
            "interactiveOnly": interactive_only,
        },
    )


async def browser_selectors(
    *,
    env_id: str,
    snapshot_id: str,
    frame_id: str,
    data_nrd: str,
    proof_root: str | Path,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-{env_id}")
    element = _element_for_handle(
        root, snapshot_id=snapshot_id, frame_id=frame_id, data_nrd=data_nrd
    )
    selectors = _selectors_for_element(element)
    row = {
        "envId": env_id,
        "snapshotId": snapshot_id,
        "frameId": frame_id,
        "dataNrd": data_nrd,
        "selectors": selectors,
        "diagnostic": True,
    }
    _append_jsonl(root / "browser" / "selectors.jsonl", row)
    return _finish_command(
        root,
        command="browser.selectors",
        status="passed",
        payload=row,
        ids={"envId": env_id, "snapshotId": snapshot_id, "dataNrd": data_nrd},
    )


async def browser_nrd_action(
    *,
    env_id: str,
    action: str,
    snapshot_id: str,
    frame_id: str,
    data_nrd: str,
    proof_root: str | Path,
    base_url: str | None = None,
    value: str | None = None,
    post_snapshot: bool = True,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-{env_id}")
    record = _load_env(root, env_id)
    env = _remote_env(record, base_url=base_url)
    handle = _handle(root, snapshot_id, frame_id, data_nrd)
    if action == "click":
        request = BrowserClickNrdRequest(handle=handle, post_snapshot=post_snapshot)
        command = "browser.click-nrd"
    elif action == "fill":
        if value is None:
            raise ValueError("fill-nrd requires a value")
        request = BrowserFillNrdRequest(
            handle=handle, value=value, post_snapshot=post_snapshot
        )
        command = "browser.fill-nrd"
    elif action == "select":
        if value is None:
            raise ValueError("select-nrd requires a value")
        request = BrowserSelectNrdRequest(
            handle=handle, value=value, post_snapshot=post_snapshot
        )
        command = "browser.select-nrd"
    else:
        raise ValueError(f"Unsupported browser nrd action {action!r}")
    response = await env._run_extension_action(
        request, BrowserActionResponse, timeout=60
    )
    artifacts: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "envId": env_id,
        "action": action,
        "snapshotId": snapshot_id,
        "frameId": frame_id,
        "dataNrd": data_nrd,
        "performed": response.status == "performed",
    }
    if response.post_snapshot is not None:
        artifacts.extend(_write_snapshot(root, response.post_snapshot))
        payload["postSnapshotId"] = response.post_snapshot.snapshot_id
    status = "passed" if response.post_snapshot is not None else "needs_review"
    warnings = (
        []
        if response.post_snapshot is not None
        else ["browser_action_post_snapshot_missing"]
    )
    _append_jsonl(root / "browser" / "actions.jsonl", payload)
    return _finish_command(
        root,
        command=command,
        status=status,
        payload=payload,
        artifacts=artifacts,
        warnings=warnings,
        ids={
            "envId": env_id,
            "snapshotId": snapshot_id,
            "dataNrd": data_nrd,
            "postSnapshotId": payload.get("postSnapshotId"),
        },
    )


async def browser_diff(
    *,
    env_id: str,
    before: str,
    after: str,
    proof_root: str | Path,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-{env_id}")
    diff = _diff_visible_text(root, before, after)
    row = {"envId": env_id, "before": before, "after": after, **diff}
    _append_jsonl(root / "browser" / "snapshot-diffs.jsonl", row)
    return _finish_command(
        root,
        command="browser.diff",
        status="passed",
        payload=row,
        ids={"envId": env_id, "beforeSnapshotId": before, "afterSnapshotId": after},
    )


async def browser_screenshot(
    *,
    env_id: str,
    proof_root: str | Path,
    base_url: str | None = None,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-{env_id}")
    record = _load_env(root, env_id)
    env = _remote_env(record, base_url=base_url)
    try:
        screenshot = await env._run_extension_action(
            BrowserScreenshotRequest(
                timeout_ms=BROWSER_WORKBENCH_SCREENSHOT_TIMEOUT_MS
            ),
            BrowserScreenshotResponse,
            timeout=75,
        )
    except Exception as exc:
        row = {
            "envId": env_id,
            "captureSupported": False,
            "status": "failed",
            "error": _redact_sensitive_text(str(exc)),
        }
        _append_jsonl(root / "browser" / "screenshots.jsonl", row)
        return _finish_command(
            root,
            command="browser.screenshot",
            status="needs_review",
            payload=row,
            warnings=["browser_screenshot_capture_failed"],
            ids={"envId": env_id},
        )
    data = _decode_base64_content(screenshot.base64_content)
    path = root / "browser" / "screenshots" / f"{uuid.uuid4().hex}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    artifact = _artifact(root, path, "browser-screenshot")
    row = {
        "envId": env_id,
        "path": artifact["path"],
        "sha256": artifact["sha256"],
        "mimeType": screenshot.mime_type,
        "timestamp": screenshot.timestamp,
    }
    _append_jsonl(root / "browser" / "screenshots.jsonl", row)
    return _finish_command(
        root,
        command="browser.screenshot",
        status="passed",
        payload=row,
        artifacts=[artifact],
        ids={"envId": env_id},
    )


async def browser_downloads(
    *,
    env_id: str,
    proof_root: str | Path,
    base_url: str | None = None,
) -> BrowserWorkbenchCommandResult:
    root = _browser_root(proof_root, f"browser-{env_id}")
    record = _load_env(root, env_id)
    env = _remote_env(record, base_url=base_url)
    started_after = _proof_root_started_after(root)
    response = await env._run_extension_action(
        BrowserDownloadsRequest(started_after=started_after),
        BrowserDownloadsResponse,
        timeout=30,
    )
    command_id = f"cmd_{uuid.uuid4().hex}"
    download_artifacts: list[dict[str, Any]] = []
    sanitized_downloads: list[dict[str, Any]] = []
    download_dir = root / "downloads" / command_id
    warnings = []
    stale_download_count = 0
    for index, download in enumerate(response.downloads):
        if not _download_is_in_scope(download, started_after):
            stale_download_count += 1
            continue
        sanitized = {
            key: value
            for key, value in download.items()
            if key not in {"local_path", "filename", "url", "final_url"}
        }
        if url := download.get("url"):
            sanitized["redactedUrl"] = _redact_sensitive_text(_redact_url(str(url)))
        if final_url := download.get("final_url"):
            sanitized["redactedFinalUrl"] = _redact_sensitive_text(
                _redact_url(str(final_url))
            )
        local_path_value = download.get("local_path") or download.get("filename")
        copied_artifact: dict[str, Any] | None = None
        if isinstance(local_path_value, str) and local_path_value:
            local_path = Path(local_path_value).expanduser()
            if local_path.exists() and local_path.is_file():
                download_dir.mkdir(parents=True, exist_ok=True)
                file_name = str(
                    sanitized.get("file_name")
                    or sanitized.get("fileName")
                    or local_path.name
                    or f"download-{index}"
                )
                destination = download_dir / _safe_slug(file_name)
                if not destination.suffix and local_path.suffix:
                    destination = destination.with_suffix(local_path.suffix)
                shutil.copyfile(local_path, destination)
                copied_artifact = _artifact(root, destination, "browser-download")
                copied_artifact["sensitive"] = True
                download_artifacts.append(copied_artifact)
                sanitized["path"] = copied_artifact["path"]
                sanitized["sha256"] = copied_artifact["sha256"]
                sanitized["byteSize"] = destination.stat().st_size
            else:
                warnings.append("download_local_path_unavailable")
        else:
            warnings.append("download_local_path_missing")
        sanitized_downloads.append(sanitized)
    row = {
        "envId": env_id,
        "downloads": sanitized_downloads,
        "captureSupported": response.capture_supported,
        "startedAfter": started_after,
        "staleDownloadCount": stale_download_count,
        "warning": response.warning,
    }
    _append_jsonl(root / "downloads.jsonl", row)
    status = "passed" if download_artifacts else "needs_review"
    if response.warning:
        warnings.append(response.warning)
    if not response.downloads:
        warnings.append("download_capture_empty")
    elif not download_artifacts:
        warnings.append("download_bytes_not_materialized")
    return _finish_command(
        root,
        command="browser.downloads",
        status=status,
        payload=row,
        artifacts=download_artifacts,
        warnings=warnings,
        command_id=command_id,
        ids={"envId": env_id},
    )

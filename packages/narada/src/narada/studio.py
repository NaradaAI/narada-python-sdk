from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit, urlunsplit

import aiohttp
from pydantic import BaseModel

from narada.agent import Agent
from narada.environment import Environment
from narada.workbench import (
    _default_out_dir,
    _redact_sensitive_text,
    _safe_slug,
    _sha256_file,
    _sha256_json,
    _update_manifest_hash,
    _write_json,
    append_command,
    default_api_base_url,
    default_auth_headers,
    materialize_execution_trace_context,
)


class AgentStudioWorkbenchError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class StudioCommandResult:
    status: str
    proof_root: Path | None
    payload: dict[str, Any]
    command_id: str | None = None


class AgentStudioWorkbenchClient:
    def __init__(
        self,
        *,
        auth_headers: dict[str, str] | None = None,
        base_url: str | None = None,
        session_factory: Callable[[], Any] = aiohttp.ClientSession,
    ) -> None:
        self.auth_headers = (
            auth_headers if auth_headers is not None else default_auth_headers()
        )
        self.base_url = (base_url or default_api_base_url()).rstrip("/")
        self.session_factory = session_factory

    async def list_items(self, *, parent_path: str = "/") -> list[dict[str, Any]]:
        payload = await self._request_json(
            "GET",
            "/agent-studio/items",
            query={"parentPath": parent_path},
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise AgentStudioWorkbenchError(
                "Agent Studio list response did not contain items"
            )
        return [item for item in items if isinstance(item, dict)]

    async def resolve_path(self, *, path: str) -> dict[str, Any]:
        payload = await self._request_json(
            "GET",
            "/agent-studio/resolve-path",
            query={"path": path},
        )
        return _extract_item(payload)

    async def get_item(self, *, item_id: str) -> dict[str, Any]:
        payload = await self._request_json("GET", f"/agent-studio/items/{item_id}")
        return _extract_item(payload)

    async def create_python_item(
        self,
        *,
        name: str,
        parent_path: str,
        code: str,
        variables: list[Any] | None = None,
    ) -> str:
        payload = await self._request_json(
            "POST",
            "/agent-studio/items",
            json_body={
                "type": "file",
                "name": name,
                "parentPath": parent_path,
                "fileType": "pythonAgent",
                "fileData": {"code": code, "variables": variables or []},
            },
        )
        item_id = payload.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise AgentStudioWorkbenchError(
                "Agent Studio create response did not contain id"
            )
        return item_id

    async def update_python_item(
        self,
        *,
        item_id: str,
        code: str,
        variables: list[Any] | None = None,
    ) -> None:
        await self._request_json(
            "POST",
            f"/agent-studio/items/{item_id}/update-file-data",
            json_body={
                "fileData": {
                    "code": code,
                    "variables": variables or [],
                }
            },
            expect_empty=True,
        )

    async def delete_item(self, *, item_id: str) -> None:
        await self._request_json(
            "POST",
            "/agent-studio/delete-items",
            json_body={"ids": [item_id]},
            expect_empty=True,
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        expect_empty: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        async with self.session_factory() as session:
            request = getattr(session, method.lower())
            kwargs: dict[str, Any] = {"headers": self.auth_headers}
            if json_body is not None:
                kwargs["json"] = json_body
            async with request(url, **kwargs) as response:
                text = await response.text()
                if response.status >= 400:
                    raise AgentStudioWorkbenchError(
                        _redact_sensitive_text(
                            f"Agent Studio request failed with HTTP {response.status}: {text}"
                        ),
                        status=response.status,
                    )
                if expect_empty or response.status == 204:
                    return {}
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise AgentStudioWorkbenchError(
                        f"Agent Studio response was not JSON for {path}"
                    ) from exc
        if not isinstance(payload, dict):
            raise AgentStudioWorkbenchError(
                f"Agent Studio response was not an object for {path}"
            )
        return payload


def _extract_item(payload: dict[str, Any]) -> dict[str, Any]:
    item = payload.get("item")
    if not isinstance(item, dict):
        raise AgentStudioWorkbenchError("Agent Studio response did not contain item")
    return item


def _list_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    shared_with = item.get("sharedWithEmails")
    summary_keys = (
        "id",
        "type",
        "name",
        "parentPath",
        "ownerEmail",
        "ownerName",
        "fileType",
        "targetItemId",
        "targetFileType",
        "isPublic",
        "createdAt",
        "updatedAt",
    )
    summary = {key: item[key] for key in summary_keys if key in item}
    if isinstance(shared_with, list):
        summary["sharedWithCount"] = len(shared_with)
    return summary


def _item_code(item: dict[str, Any]) -> str:
    if item.get("type") != "file" or item.get("fileType") != "pythonAgent":
        raise AgentStudioWorkbenchError("Agent Studio item is not a Python agent file")
    file_data = item.get("fileData")
    if not isinstance(file_data, dict) or not isinstance(file_data.get("code"), str):
        raise AgentStudioWorkbenchError(
            "Python agent item did not contain fileData.code"
        )
    return file_data["code"]


def _item_variables(item: dict[str, Any]) -> list[Any]:
    file_data = item.get("fileData")
    if not isinstance(file_data, dict):
        return []
    variables = file_data.get("variables")
    return variables if isinstance(variables, list) else []


def _item_path(item: dict[str, Any]) -> str:
    parent_path = item.get("parentPath")
    name = item.get("name")
    if not isinstance(parent_path, str) or not isinstance(name, str):
        raise AgentStudioWorkbenchError(
            "Agent Studio item did not contain parentPath/name"
        )
    return f"{parent_path}{name}"


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_jsonable_value(inner) for inner in value]
    return value


def _url_origin(value: str) -> str:
    split = urlsplit(value)
    return urlunsplit((split.scheme, split.netloc, "", "", ""))


def _auth_mode(headers: dict[str, str]) -> str:
    normalized = {key.lower(): value for key, value in headers.items()}
    if normalized.get("x-api-key"):
        return "api-key"
    if normalized.get("authorization"):
        return "bearer"
    return "none"


def _slash_command_path(item: dict[str, Any]) -> str:
    owner_email = item.get("ownerEmail")
    if not isinstance(owner_email, str) or not owner_email:
        raise AgentStudioWorkbenchError("Agent Studio item did not contain ownerEmail")
    return f"/{owner_email}{_item_path(item)}"


def _python_file_data(code: str, variables: list[Any] | None = None) -> dict[str, Any]:
    return {"code": code, "variables": variables or []}


def _local_code_and_hash(path: str | Path) -> tuple[str, str]:
    local_path = Path(path)
    code = local_path.read_text(encoding="utf-8")
    return code, _sha256_file(local_path)


def _remote_code_hash(item: dict[str, Any]) -> str:
    return _sha256_json(_python_file_data(_item_code(item), _item_variables(item)))


def _studio_root(proof_root: str | Path | None, label: str) -> Path | None:
    if proof_root is None:
        return None
    root = Path(proof_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_remote_item(root: Path, item: dict[str, Any]) -> str:
    item_id = str(item.get("id") or "unknown-item")
    path = root / "agent-studio" / "items" / _safe_slug(item_id) / "remote.json"
    _write_json(path, item)
    return path.relative_to(root).as_posix()


def _append_studio_command(
    root: Path | None,
    *,
    command: str,
    status: str,
    payload: dict[str, Any],
    client: AgentStudioWorkbenchClient | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    taints: list[str] | None = None,
) -> str | None:
    if root is None:
        return None
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    if client is not None:
        inputs = {
            **inputs,
            "apiBaseUrlOrigin": _url_origin(client.base_url),
            "authMode": _auth_mode(client.auth_headers),
        }
    row = append_command(
        root,
        command=command,
        status=status,
        artifacts=artifacts,
        warnings=warnings,
        taints=taints,
        ids=payload.get("ids") if isinstance(payload.get("ids"), dict) else {},
        inputs=inputs,
    )
    return str(row["commandId"])


def _assert_created_by_command(root: Path, *, command_id: str, item_id: str) -> None:
    commands_path = root / "commands.jsonl"
    if not commands_path.exists():
        raise AgentStudioWorkbenchError("Proof root does not contain commands.jsonl")
    for line in commands_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("commandId") != command_id:
            continue
        ids = row.get("ids")
        inputs = row.get("inputs")
        if (
            row.get("command") == "studio.upsert-python"
            and row.get("status") == "passed"
            and isinstance(ids, dict)
            and isinstance(inputs, dict)
            and ids.get("itemId") == item_id
            and ids.get("remoteCodeHash") is None
            and inputs.get("apply") is True
            and inputs.get("updateItemId") is None
        ):
            return
        raise AgentStudioWorkbenchError(
            "Referenced command did not create the requested item in this proof root"
        )
    raise AgentStudioWorkbenchError("Referenced command id was not found in proof root")


async def studio_list(
    *,
    parent_path: str = "/",
    proof_root: str | Path | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-list")
    items = [
        _list_item_summary(item)
        for item in await resolved_client.list_items(parent_path=parent_path)
    ]
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        output_path = root / "agent-studio" / "list.json"
        _write_json(output_path, {"items": items})
        artifacts.append(
            {
                "path": output_path.relative_to(root).as_posix(),
                "role": "agent-studio-list",
            }
        )
    payload = {
        "schemaVersion": 1,
        "status": "passed",
        "items": items,
        "proofRoot": str(root) if root is not None else None,
        "inputs": {"parentPath": parent_path},
    }
    command_id = _append_studio_command(
        root,
        command="studio.list",
        status="passed",
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
    )
    return StudioCommandResult("passed", root, payload, command_id)


async def studio_resolve(
    *,
    path: str,
    proof_root: str | Path | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-resolve")
    item = await resolved_client.resolve_path(path=path)
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        artifacts.append(
            {"path": _write_remote_item(root, item), "role": "remote-item"}
        )
    payload = {
        "schemaVersion": 1,
        "status": "passed",
        "item": item,
        "proofRoot": str(root) if root is not None else None,
        "ids": {"itemId": item.get("id")},
        "inputs": {"path": path},
    }
    command_id = _append_studio_command(
        root,
        command="studio.resolve",
        status="passed",
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
    )
    return StudioCommandResult("passed", root, payload, command_id)


async def studio_get(
    *,
    item_id: str,
    proof_root: str | Path | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-get")
    item = await resolved_client.get_item(item_id=item_id)
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        artifacts.append(
            {"path": _write_remote_item(root, item), "role": "remote-item"}
        )
    payload = {
        "schemaVersion": 1,
        "status": "passed",
        "item": item,
        "proofRoot": str(root) if root is not None else None,
        "ids": {"itemId": item.get("id")},
        "inputs": {"itemId": item_id},
    }
    command_id = _append_studio_command(
        root,
        command="studio.get",
        status="passed",
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
    )
    return StudioCommandResult("passed", root, payload, command_id)


async def studio_export(
    *,
    item_id: str,
    out: str | Path,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    item = await resolved_client.get_item(item_id=item_id)
    code = _item_code(item)
    item_dir = root / "agent-studio" / "items" / _safe_slug(item_id)
    item_dir.mkdir(parents=True, exist_ok=True)
    export_path = item_dir / "export.py"
    export_path.write_text(code, encoding="utf-8")
    remote_path = item_dir / "remote.json"
    _write_json(remote_path, item)
    payload = {
        "schemaVersion": 1,
        "status": "passed",
        "proofRoot": str(root),
        "exportPath": str(export_path),
        "localPath": export_path.relative_to(root).as_posix(),
        "ids": {"itemId": item_id, "remoteCodeHash": _remote_code_hash(item)},
        "inputs": {"itemId": item_id},
    }
    command_id = _append_studio_command(
        root,
        command="studio.export",
        status="passed",
        payload=payload,
        client=resolved_client,
        artifacts=[
            {"path": export_path.relative_to(root).as_posix(), "role": "python-source"},
            {"path": remote_path.relative_to(root).as_posix(), "role": "remote-item"},
        ],
    )
    return StudioCommandResult("passed", root, payload, command_id)


async def studio_diff(
    *,
    item_id: str,
    file: str | Path,
    proof_root: str | Path | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-diff")
    item = await resolved_client.get_item(item_id=item_id)
    remote_code = _item_code(item)
    local_code, local_hash = _local_code_and_hash(file)
    remote_hash = _remote_code_hash(item)
    matches = local_code == remote_code
    status = "passed" if matches else "needs_review"
    report = {
        "schemaVersion": 1,
        "status": status,
        "matches": matches,
        "itemId": item_id,
        "localSha256": local_hash,
        "remoteCodeHash": remote_hash,
    }
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        diff_path = root / "agent-studio" / "diff.json"
        _write_json(diff_path, report)
        artifacts.append(
            {"path": diff_path.relative_to(root).as_posix(), "role": "diff"}
        )
    payload = {
        **report,
        "proofRoot": str(root) if root is not None else None,
        "ids": {
            "itemId": item_id,
            "localSha256": local_hash,
            "remoteCodeHash": remote_hash,
        },
        "inputs": {"itemId": item_id, "file": str(file)},
    }
    command_id = _append_studio_command(
        root,
        command="studio.diff",
        status=status,
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
    )
    return StudioCommandResult(status, root, payload, command_id)


async def studio_upsert_python(
    *,
    name: str,
    parent_path: str,
    file: str | Path,
    apply: bool,
    proof_root: str | Path | None = None,
    update_item_id: str | None = None,
    expected_remote_code_hash: str | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-upsert")
    code, local_hash = _local_code_and_hash(file)
    item_path = f"{parent_path}{name}"
    existing_item: dict[str, Any] | None = None
    warnings: list[str] = []
    try:
        existing_item = await resolved_client.resolve_path(path=item_path)
    except AgentStudioWorkbenchError as exc:
        if exc.status != 404:
            raise

    action = "create" if existing_item is None else "update"
    item_id: str | None = None
    remote_hash: str | None = None
    if existing_item is not None:
        item_id = str(existing_item.get("id") or "")
        _item_code(existing_item)
        remote_hash = _remote_code_hash(existing_item)
        if not update_item_id:
            raise AgentStudioWorkbenchError(
                "Target path already exists; pass --update-item-id and --expected-remote-code-hash"
            )
        if item_id != update_item_id:
            raise AgentStudioWorkbenchError(
                "Resolved item id did not match --update-item-id"
            )
        if expected_remote_code_hash != remote_hash:
            raise AgentStudioWorkbenchError(
                "Remote code hash did not match expected hash"
            )

    if not apply:
        status = "passed"
    elif existing_item is None:
        item_id = await resolved_client.create_python_item(
            name=name,
            parent_path=parent_path,
            code=code,
        )
        status = "passed"
    else:
        await resolved_client.update_python_item(
            item_id=item_id or update_item_id or "",
            code=code,
            variables=_item_variables(existing_item),
        )
        status = "passed"

    report = {
        "schemaVersion": 1,
        "status": status,
        "action": action,
        "applied": apply,
        "itemId": item_id,
        "path": item_path,
        "localSha256": local_hash,
        "remoteCodeHash": remote_hash,
    }
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        report_path = root / "agent-studio" / "lifecycle-report.json"
        _write_json(report_path, report)
        artifacts.append(
            {
                "path": report_path.relative_to(root).as_posix(),
                "role": "lifecycle-report",
            }
        )
        if existing_item is not None:
            artifacts.append(
                {
                    "path": _write_remote_item(root, existing_item),
                    "role": "remote-item-before",
                }
            )
    payload = {
        **report,
        "proofRoot": str(root) if root is not None else None,
        "ids": {
            "itemId": item_id,
            "localSha256": local_hash,
            "remoteCodeHash": remote_hash,
        },
        "inputs": {
            "name": name,
            "parentPath": parent_path,
            "file": str(file),
            "apply": apply,
            "updateItemId": update_item_id,
        },
    }
    command_id = _append_studio_command(
        root,
        command="studio.upsert-python",
        status=status,
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
        warnings=warnings,
    )
    return StudioCommandResult(status, root, payload, command_id)


async def studio_run(
    *,
    item_id: str,
    proof_root: str | Path | None,
    prompt_suffix: str | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    item = await resolved_client.get_item(item_id=item_id)
    _item_code(item)
    slash_path = _slash_command_path(item)
    prompt = slash_path if not prompt_suffix else f"{slash_path}\n{prompt_suffix}"
    environment = Environment(
        auth_headers=resolved_client.auth_headers,
        base_url=resolved_client.base_url,
    )
    response = await Agent(environment=environment).run(prompt)
    context = response.execution_trace_context
    if context is None:
        raise AgentStudioWorkbenchError(
            "Agent run did not return executionTraceContext"
        )
    root = (
        Path(proof_root)
        if proof_root is not None
        else _default_out_dir(f"studio-run-{item_id}")
    )
    materialized = await materialize_execution_trace_context(
        context,
        out=root,
        label=f"studio-run-{item_id}",
        source_run={
            "type": "remote-dispatch",
            "authority": "agent-run-response",
            "requestId": response.request_id,
            "status": response.status,
        },
        auth_headers=resolved_client.auth_headers,
        base_url=resolved_client.base_url,
    )
    run_report = {
        "schemaVersion": 1,
        "status": response.status,
        "itemId": item_id,
        "slashPath": slash_path,
        "requestId": response.request_id,
        "text": response.text,
        "output": _jsonable_value(response.output),
        "structuredOutput": _jsonable_value(response.structured_output),
        "executionTraceContext": context,
    }
    run_path = materialized.path / "agent-studio" / "run.json"
    _write_json(run_path, run_report)
    artifacts = [
        {
            "path": run_path.relative_to(materialized.path).as_posix(),
            "role": "agent-studio-run",
        },
        {"path": _write_remote_item(materialized.path, item), "role": "remote-item"},
    ]
    materialization_report = getattr(materialized, "report", {})
    materialization_status = (
        str(materialization_report.get("status", "unknown"))
        if isinstance(materialization_report, dict)
        else "unknown"
    )
    status = "passed" if response.status == "success" else response.status
    if materialization_status in {"failed", "tainted", "needs_review"}:
        status = materialization_status
    payload = {
        "schemaVersion": 1,
        "status": status,
        "proofRoot": str(materialized.path),
        "requestId": response.request_id,
        "itemId": item_id,
        "slashPath": slash_path,
        "materializationStatus": materialization_status,
        "runSubstrate": {
            "type": "sdk-client-remote-dispatch",
            "requiresActiveClient": True,
        },
        "ids": {"itemId": item_id, "requestId": response.request_id},
        "inputs": {
            "itemId": item_id,
            "promptSuffix": prompt_suffix,
            "runSubstrate": "sdk-client-remote-dispatch",
            "requiresActiveClient": True,
        },
    }
    command_id = _append_studio_command(
        materialized.path,
        command="studio.run",
        status=payload["status"],
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
        warnings=["requires-active-client"],
    )
    _update_manifest_hash(
        materialized.path, "commandLedgerHash", materialized.path / "commands.jsonl"
    )
    return StudioCommandResult(
        payload["status"], materialized.path, payload, command_id
    )


async def studio_delete(
    *,
    item_id: str,
    expected_name: str,
    created_by_command_id: str,
    proof_root: str | Path | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-delete")
    item = await resolved_client.get_item(item_id=item_id)
    if item.get("name") != expected_name:
        raise AgentStudioWorkbenchError(
            "Remote item name did not match --expected-name"
        )
    if not created_by_command_id.startswith("cmd_"):
        raise AgentStudioWorkbenchError(
            "--created-by-command-id must be a workbench command id"
        )
    if root is not None:
        _assert_created_by_command(
            root, command_id=created_by_command_id, item_id=item_id
        )
    await resolved_client.delete_item(item_id=item_id)
    report = {
        "schemaVersion": 1,
        "status": "passed",
        "itemId": item_id,
        "expectedName": expected_name,
        "createdByCommandId": created_by_command_id,
    }
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        cleanup_path = root / "agent-studio" / "cleanup.json"
        _write_json(cleanup_path, report)
        artifacts.append(
            {"path": cleanup_path.relative_to(root).as_posix(), "role": "cleanup"}
        )
        artifacts.append(
            {
                "path": _write_remote_item(root, item),
                "role": "remote-item-before-delete",
            }
        )
    payload = {
        **report,
        "proofRoot": str(root) if root is not None else None,
        "ids": {"itemId": item_id, "createdByCommandId": created_by_command_id},
        "inputs": {"itemId": item_id, "expectedName": expected_name},
    }
    command_id = _append_studio_command(
        root,
        command="studio.delete",
        status="passed",
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
    )
    return StudioCommandResult("passed", root, payload, command_id)

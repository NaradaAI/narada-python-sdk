from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit, urlunsplit

import aiohttp
from pydantic import BaseModel

from narada.agent import Agent
from narada.environment import Environment
from narada.project_sync import (
    ProjectPackage,
    build_project_package,
    diff_project_package,
    extract_project_from_runtime,
    scan_project_package_findings,
    write_exported_project,
)
from narada.tracing import trace
from narada.workbench import (
    _default_out_dir,
    _redact_sensitive_text,
    _safe_slug,
    _sha256_file,
    _sha256_json,
    _update_manifest_hash,
    _write_json,
    _write_redaction_report,
    append_command,
    default_api_base_url,
    default_auth_headers,
)

_SEARCH_LIMIT_CAPS = {
    "max_depth": 8,
    "max_items": 1000,
    "max_content_items": 100,
}


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


def _is_folder_item(item: dict[str, Any]) -> bool:
    return item.get("type") == "folder"


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


def _item_search_path(item: dict[str, Any]) -> str:
    try:
        return _item_path(item)
    except AgentStudioWorkbenchError:
        return ""


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


def _search_tokens(query: str) -> list[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in query)
    return [token for token in normalized.split() if token]


def _text_similarity(query: str, value: str) -> int:
    if not query or not value:
        return 0
    return int(SequenceMatcher(None, query.lower(), value.lower()).ratio() * 30)


def _first_snippet(text: str, tokens: list[str], *, radius: int = 80) -> str | None:
    lower = text.lower()
    match_index = -1
    for token in tokens:
        match_index = lower.find(token)
        if match_index >= 0:
            break
    if match_index < 0:
        return None
    start = max(0, match_index - radius)
    end = min(len(text), match_index + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return _redact_sensitive_text(f"{prefix}{text[start:end]}{suffix}")


def _score_metadata_match(
    item: dict[str, Any], query: str, tokens: list[str]
) -> tuple[int, list[str], list[dict[str, str]]]:
    name = str(item.get("name") or "")
    path = _item_search_path(item)
    item_type = str(item.get("type") or "")
    file_type = str(item.get("fileType") or item.get("targetFileType") or "")
    fields = {
        "name": name,
        "path": path,
        "type": item_type,
        "fileType": file_type,
    }
    score = 0
    matched_fields: set[str] = set()
    snippets: list[dict[str, str]] = []
    query_lower = query.lower()

    for field, value in fields.items():
        value_lower = value.lower()
        if not value_lower:
            continue
        field_score = 0
        if query_lower and query_lower in value_lower:
            field_score += 80 if field == "name" else 60
        for token in tokens:
            if token in value_lower:
                field_score += 20 if field == "name" else 12
        similarity = _text_similarity(query, value)
        if field in {"name", "path"} and similarity >= 18:
            field_score += similarity
        if field_score:
            matched_fields.add(field)
            snippet = _first_snippet(value, tokens)
            if snippet is not None:
                snippets.append({"field": field, "text": snippet})
        score += field_score

    return score, sorted(matched_fields), snippets


def _score_content_match(
    code: str, query: str, tokens: list[str]
) -> tuple[int, list[dict[str, str]]]:
    code_lower = code.lower()
    query_lower = query.lower()
    score = 0
    if query_lower and query_lower in code_lower:
        score += 50
    for token in tokens:
        if token in code_lower:
            score += 12
    snippet = _first_snippet(code, tokens, radius=100)
    snippets = [{"field": "content", "text": snippet}] if snippet else []
    return score, snippets


def _redact_search_text(value: Any) -> Any:
    if value is None:
        return None
    return _redact_sensitive_text(str(value))


def _search_resolution_status(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "no_match"
    if len(candidates) == 1:
        return "single_candidate"
    top_score = int(candidates[0].get("score") or 0)
    second_score = int(candidates[1].get("score") or 0)
    if second_score >= max(top_score - 10, int(top_score * 0.8)):
        return "needs_user_choice"
    return "single_candidate"


def _studio_root(proof_root: str | Path | None, label: str) -> Path | None:
    if proof_root is None:
        return None
    root = Path(proof_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize_parent_path(parent_path: str) -> str:
    normalized = parent_path or "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if not normalized.endswith("/"):
        normalized = f"{normalized}/"
    return normalized


def _write_remote_item(root: Path, item: dict[str, Any]) -> str:
    item_id = str(item.get("id") or "unknown-item")
    path = root / "agent-studio" / "items" / _safe_slug(item_id) / "remote.json"
    _write_json(path, item)
    return path.relative_to(root).as_posix()


def _write_remote_item_ref(
    root: Path, item: dict[str, Any], role: str
) -> dict[str, Any]:
    relative_path = _write_remote_item(root, item)
    return _artifact_ref(root, root / relative_path, role)


def _append_studio_command(
    root: Path | None,
    *,
    command: str,
    status: str,
    payload: dict[str, Any],
    client: AgentStudioWorkbenchClient | None = None,
    command_id: str | None = None,
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
        command_id=command_id,
        artifacts=artifacts,
        warnings=warnings,
        taints=taints,
        ids=payload.get("ids") if isinstance(payload.get("ids"), dict) else {},
        inputs=inputs,
    )
    return str(row["commandId"])


def _artifact_ref(root: Path, path: Path, role: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "sha256": _sha256_file(path),
    }


def _refresh_redaction_report(root: Path | None) -> None:
    if root is not None:
        _write_redaction_report(root)


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
        allowed_create_commands = {
            "studio.upsert-python",
            "studio.sync-python-project",
        }
        if (
            row.get("command") in allowed_create_commands
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
    _refresh_redaction_report(root)
    return StudioCommandResult("passed", root, payload, command_id)


async def _collect_search_items(
    client: AgentStudioWorkbenchClient,
    *,
    parent_path: str,
    max_depth: int,
    max_items: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    normalized_parent_path = _normalize_parent_path(parent_path)
    queue: list[tuple[str, int]] = [(normalized_parent_path, 0)]
    visited_paths: set[str] = set()
    items: list[dict[str, Any]] = []

    while queue:
        current_parent_path, depth = queue.pop(0)
        if current_parent_path in visited_paths:
            continue
        visited_paths.add(current_parent_path)
        if depth > max_depth:
            warnings.append(f"max-depth-reached:{current_parent_path}")
            continue
        for item in await client.list_items(parent_path=current_parent_path):
            items.append(item)
            if len(items) >= max_items:
                warnings.append("max-items-reached")
                return items
            if _is_folder_item(item) and depth < max_depth:
                folder_path = _normalize_parent_path(_item_search_path(item))
                if folder_path not in visited_paths:
                    queue.append((folder_path, depth + 1))
    return items


async def studio_search(
    *,
    query: str,
    parent_path: str = "/",
    content: bool = False,
    max_depth: int = 3,
    max_items: int = 200,
    max_content_items: int = 25,
    proof_root: str | Path | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-search")
    normalized_parent_path = _normalize_parent_path(parent_path)
    warnings: list[str] = []
    if max_depth < 0:
        raise AgentStudioWorkbenchError("--max-depth must be non-negative")
    if max_items < 1:
        raise AgentStudioWorkbenchError("--max-items must be at least 1")
    if max_content_items < 0:
        raise AgentStudioWorkbenchError("--max-content-items must be non-negative")
    if max_depth > _SEARCH_LIMIT_CAPS["max_depth"]:
        warnings.append(f"max-depth-capped:{_SEARCH_LIMIT_CAPS['max_depth']}")
        max_depth = _SEARCH_LIMIT_CAPS["max_depth"]
    if max_items > _SEARCH_LIMIT_CAPS["max_items"]:
        warnings.append(f"max-items-capped:{_SEARCH_LIMIT_CAPS['max_items']}")
        max_items = _SEARCH_LIMIT_CAPS["max_items"]
    if max_content_items > _SEARCH_LIMIT_CAPS["max_content_items"]:
        warnings.append(
            f"max-content-items-capped:{_SEARCH_LIMIT_CAPS['max_content_items']}"
        )
        max_content_items = _SEARCH_LIMIT_CAPS["max_content_items"]
    tokens = _search_tokens(query)
    if not tokens:
        raise AgentStudioWorkbenchError("--query must contain searchable text")

    items = await _collect_search_items(
        resolved_client,
        parent_path=normalized_parent_path,
        max_depth=max_depth,
        max_items=max_items,
        warnings=warnings,
    )
    content_items_checked = 0
    candidates: list[dict[str, Any]] = []
    for item in items:
        metadata_score, matched_fields, snippets = _score_metadata_match(
            item, query, tokens
        )
        score = metadata_score
        item_type = str(item.get("type") or "")
        file_type = str(item.get("fileType") or item.get("targetFileType") or "")
        item_id = str(item.get("id") or "")
        if content and item_type == "file" and file_type == "pythonAgent" and item_id:
            if content_items_checked >= max_content_items:
                warnings.append("max-content-items-reached")
            else:
                content_items_checked += 1
                try:
                    full_item = await resolved_client.get_item(item_id=item_id)
                    content_score, content_snippets = _score_content_match(
                        _item_code(full_item), query, tokens
                    )
                    if content_score:
                        score += content_score
                        matched_fields = sorted({*matched_fields, "content"})
                        snippets.extend(content_snippets)
                except AgentStudioWorkbenchError as exc:
                    warnings.append(f"content-unavailable:{item_id}:{exc.status}")
        if score <= 0:
            continue
        candidates.append(
            {
                "itemId": item_id,
                "name": _redact_search_text(item.get("name")),
                "path": _redact_search_text(_item_search_path(item)),
                "type": item_type,
                "fileType": file_type or None,
                "score": score,
                "matchedFields": matched_fields,
                "snippets": snippets[:3],
                "ownerEmail": _redact_search_text(item.get("ownerEmail")),
                "isShortcut": item_type.endswith("Shortcut"),
            }
        )

    candidates.sort(
        key=lambda candidate: (
            int(candidate.get("score") or 0),
            str(candidate.get("name") or "").lower(),
        ),
        reverse=True,
    )
    resolution_status = _search_resolution_status(candidates)
    report = {
        "schemaVersion": 1,
        "status": "passed",
        "query": _redact_search_text(query),
        "resolutionStatus": resolution_status,
        "candidates": candidates,
        "warnings": sorted(set(warnings)),
        "searchedItemCount": len(items),
        "contentSearchEnabled": content,
        "contentItemsChecked": content_items_checked,
        "limits": {
            "maxDepth": max_depth,
            "maxItems": max_items,
            "maxContentItems": max_content_items,
        },
    }
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        search_path = root / "agent-studio" / "search.json"
        _write_json(search_path, report)
        artifacts.append(_artifact_ref(root, search_path, "agent-studio-search"))
    payload = {
        **report,
        "proofRoot": str(root) if root is not None else None,
        "inputs": {
            "query": _redact_search_text(query),
            "parentPath": _redact_search_text(normalized_parent_path),
            "content": content,
            "maxDepth": max_depth,
            "maxItems": max_items,
            "maxContentItems": max_content_items,
        },
    }
    command_id = _append_studio_command(
        root,
        command="studio.search",
        status="passed",
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
        warnings=report["warnings"],
    )
    _refresh_redaction_report(root)
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
        artifacts.append(_write_remote_item_ref(root, item, "remote-item"))
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
    _refresh_redaction_report(root)
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
        artifacts.append(_write_remote_item_ref(root, item, "remote-item"))
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
    _refresh_redaction_report(root)
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
            _artifact_ref(root, export_path, "python-source"),
            _artifact_ref(root, remote_path, "remote-item"),
        ],
    )
    _refresh_redaction_report(root)
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
        artifacts.append(_artifact_ref(root, diff_path, "diff"))
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
    _refresh_redaction_report(root)
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
        artifacts.append(_artifact_ref(root, report_path, "lifecycle-report"))
        if existing_item is not None:
            artifacts.append(
                _write_remote_item_ref(root, existing_item, "remote-item-before")
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
    _refresh_redaction_report(root)
    return StudioCommandResult(status, root, payload, command_id)


def _write_project_package_artifacts(
    root: Path,
    package: ProjectPackage,
    command_id: str,
    include_runtime: bool = True,
) -> list[dict[str, Any]]:
    sync_root = root / "agent-studio" / "project-sync" / "commands" / command_id
    latest_root = root / "agent-studio" / "project-sync"
    manifest_path = sync_root / "source-manifest.json"
    report_path = sync_root / "package-report.json"
    runtime_path = sync_root / "generated-runtime.py"
    _write_json(report_path, package.package_report)
    _write_json(latest_root / "package-report.json", package.package_report)
    artifacts = [
        _artifact_ref(root, report_path, "project-package-report"),
    ]
    if include_runtime:
        _write_json(manifest_path, package.manifest)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(package.runtime_code, encoding="utf-8")
        _write_json(latest_root / "source-manifest.json", package.manifest)
        (latest_root / "generated-runtime.py").write_text(
            package.runtime_code, encoding="utf-8"
        )
        artifacts.extend(
            [
                _artifact_ref(root, manifest_path, "project-source-manifest"),
                _artifact_ref(root, runtime_path, "generated-python-runtime"),
            ]
        )
    else:
        for latest_path in (
            latest_root / "source-manifest.json",
            latest_root / "generated-runtime.py",
        ):
            latest_path.unlink(missing_ok=True)
    return artifacts


def _project_sync_redaction_status(
    root: Path, package_findings: dict[str, list[str]]
) -> tuple[str, list[str], list[str]]:
    redaction = _write_redaction_report(root)
    failures = [
        f"{finding['code']}:{finding['path']}"
        for finding in redaction["findings"]
        if finding["severity"] == "failure"
    ]
    taints = [
        f"{finding['code']}:{finding['path']}"
        for finding in redaction["findings"]
        if finding["severity"] == "taint"
    ]
    failures.extend(package_findings["failures"])
    taints.extend(package_findings["taints"])
    status = "failed" if failures else ("tainted" if taints else "passed")
    return status, failures, taints


async def studio_sync_python_project(
    *,
    local: str | Path,
    name: str,
    parent_path: str,
    entrypoint: str,
    apply: bool,
    proof_root: str | Path,
    update_item_id: str | None = None,
    expected_remote_code_hash: str | None = None,
    client: AgentStudioWorkbenchClient | None = None,
    regeneration_command: str | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-sync-python-project")
    if root is None:
        raise AgentStudioWorkbenchError("sync-python-project requires --proof-root")
    command_id = f"cmd_{uuid.uuid4().hex}"
    package = build_project_package(
        local=local,
        entrypoint=entrypoint,
        regeneration_command=regeneration_command,
    )
    package_findings = scan_project_package_findings(package)
    package_status = (
        "failed"
        if package_findings["failures"]
        else ("tainted" if package_findings["taints"] else "passed")
    )
    artifacts = _write_project_package_artifacts(
        root,
        package,
        command_id,
        include_runtime=package_status == "passed",
    )
    redaction_status, redaction_failures, redaction_taints = (
        _project_sync_redaction_status(root, package_findings)
    )
    normalized_parent_path = _normalize_parent_path(parent_path)
    item_path = f"{normalized_parent_path}{name}"
    existing_item: dict[str, Any] | None = None
    remote_hash: str | None = None
    item_id: str | None = None
    warnings: list[str] = []
    action = "create"

    if redaction_status == "passed":
        try:
            existing_item = await resolved_client.resolve_path(path=item_path)
        except AgentStudioWorkbenchError as exc:
            if exc.status != 404:
                raise

        if existing_item is not None:
            action = "update"
            item_id = str(existing_item.get("id") or "")
            _item_code(existing_item)
            remote_hash = _remote_code_hash(existing_item)
            if apply:
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

        if apply:
            if existing_item is None:
                item_id = await resolved_client.create_python_item(
                    name=name,
                    parent_path=normalized_parent_path,
                    code=package.runtime_code,
                )
            else:
                await resolved_client.update_python_item(
                    item_id=item_id or update_item_id or "",
                    code=package.runtime_code,
                    variables=_item_variables(existing_item),
                )

    status = redaction_status
    if redaction_status == "passed":
        status = "passed"
    elif apply:
        warnings.append(
            "Remote write skipped because project package did not pass redaction scan"
        )
    report = {
        "schemaVersion": 1,
        "status": status,
        "action": action,
        "applied": apply and status == "passed",
        "itemId": item_id,
        "path": item_path,
        "entrypoint": entrypoint,
        "sourceTreeSha256": package.manifest["sourceTreeSha256"],
        "runtimeSha256": package.manifest["runtimeSha256"],
        "remoteCodeHash": remote_hash,
        "redactionStatus": redaction_status,
        "redactionFailures": redaction_failures,
        "redactionTaints": redaction_taints,
        "requiresUpdateGuard": existing_item is not None and not apply,
        "suggestedUpdateItemId": item_id if existing_item is not None else None,
        "suggestedExpectedRemoteCodeHash": remote_hash
        if existing_item is not None
        else None,
    }
    lifecycle_path = (
        root
        / "agent-studio"
        / "project-sync"
        / "commands"
        / command_id
        / "sync-report.json"
    )
    _write_json(lifecycle_path, report)
    _write_json(root / "agent-studio" / "project-sync" / "sync-report.json", report)
    artifacts.append(_artifact_ref(root, lifecycle_path, "project-sync-report"))
    if existing_item is not None:
        artifacts.append(
            _write_remote_item_ref(root, existing_item, "remote-item-before")
        )
    payload = {
        **report,
        "proofRoot": str(root),
        "ids": {
            "itemId": item_id,
            "sourceTreeSha256": package.manifest["sourceTreeSha256"],
            "runtimeSha256": package.manifest["runtimeSha256"],
            "remoteCodeHash": remote_hash,
        },
        "inputs": {
            "name": name,
            "parentPath": normalized_parent_path,
            "local": str(local),
            "entrypoint": entrypoint,
            "apply": apply,
            "updateItemId": update_item_id,
        },
    }
    written_command_id = _append_studio_command(
        root,
        command="studio.sync-python-project",
        status=status,
        payload=payload,
        client=resolved_client,
        command_id=command_id,
        artifacts=artifacts,
        warnings=warnings,
        taints=redaction_taints,
    )
    _refresh_redaction_report(root)
    return StudioCommandResult(status, root, payload, written_command_id)


async def studio_project_diff(
    *,
    local: str | Path,
    item_id: str,
    proof_root: str | Path | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-project-diff")
    command_id = f"cmd_{uuid.uuid4().hex}" if root is not None else None
    item = await resolved_client.get_item(item_id=item_id)
    remote_manifest, _ = extract_project_from_runtime(_item_code(item))
    local_package = build_project_package(
        local=local,
        entrypoint=str(remote_manifest["entrypoint"]),
    )
    report = {
        **diff_project_package(
            local_package=local_package,
            remote_manifest=remote_manifest,
        ),
        "itemId": item_id,
    }
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        sync_root = (
            root / "agent-studio" / "project-sync" / "commands" / str(command_id)
        )
        diff_path = sync_root / "project-diff.json"
        manifest_path = sync_root / "source-manifest.json"
        remote_manifest_path = sync_root / "remote-source-manifest.json"
        _write_json(diff_path, report)
        _write_json(manifest_path, local_package.manifest)
        _write_json(remote_manifest_path, remote_manifest)
        latest_root = root / "agent-studio" / "project-sync"
        _write_json(latest_root / "project-diff.json", report)
        _write_json(latest_root / "source-manifest.json", local_package.manifest)
        _write_json(latest_root / "remote-source-manifest.json", remote_manifest)
        artifacts.extend(
            [
                _artifact_ref(root, diff_path, "project-diff"),
                _artifact_ref(root, manifest_path, "project-source-manifest"),
                _artifact_ref(
                    root, remote_manifest_path, "remote-project-source-manifest"
                ),
            ]
        )
    payload = {
        **report,
        "proofRoot": str(root) if root is not None else None,
        "ids": {
            "itemId": item_id,
            "localSourceTreeSha256": report["localSourceTreeSha256"],
            "remoteSourceTreeSha256": report["remoteSourceTreeSha256"],
        },
        "inputs": {"itemId": item_id, "local": str(local)},
    }
    command_id = _append_studio_command(
        root,
        command="studio.project-diff",
        status=report["status"],
        payload=payload,
        client=resolved_client,
        command_id=command_id,
        artifacts=artifacts,
    )
    _refresh_redaction_report(root)
    return StudioCommandResult(report["status"], root, payload, command_id)


async def studio_project_export(
    *,
    item_id: str,
    out: str | Path,
    proof_root: str | Path | None = None,
    client: AgentStudioWorkbenchClient | None = None,
) -> StudioCommandResult:
    resolved_client = client or AgentStudioWorkbenchClient()
    root = _studio_root(proof_root, "studio-project-export")
    command_id = f"cmd_{uuid.uuid4().hex}" if root is not None else None
    item = await resolved_client.get_item(item_id=item_id)
    manifest, files = extract_project_from_runtime(_item_code(item))
    exported = write_exported_project(out=out, files=files)
    report = {
        "schemaVersion": 1,
        "status": "passed",
        "itemId": item_id,
        "out": str(out),
        "entrypoint": manifest["entrypoint"],
        "sourceTreeSha256": manifest["sourceTreeSha256"],
        "runtimeSha256": manifest["runtimeSha256"],
        "files": exported,
    }
    artifacts: list[dict[str, Any]] = []
    if root is not None:
        sync_root = (
            root / "agent-studio" / "project-sync" / "commands" / str(command_id)
        )
        export_path = sync_root / "project-export.json"
        manifest_path = sync_root / "source-manifest.json"
        _write_json(export_path, report)
        _write_json(manifest_path, manifest)
        latest_root = root / "agent-studio" / "project-sync"
        _write_json(latest_root / "project-export.json", report)
        _write_json(latest_root / "source-manifest.json", manifest)
        artifacts.extend(
            [
                _artifact_ref(root, export_path, "project-export"),
                _artifact_ref(root, manifest_path, "project-source-manifest"),
            ]
        )
        export_files_root = sync_root / "exported-files"
        exported_for_proof = write_exported_project(out=export_files_root, files=files)
        write_exported_project(
            out=latest_root / "exported-files",
            files=files,
            allow_overwrite=True,
        )
        for row in exported_for_proof:
            artifacts.append(
                _artifact_ref(
                    root,
                    export_files_root / row["path"],
                    "project-exported-file",
                )
            )
    payload = {
        **report,
        "proofRoot": str(root) if root is not None else None,
        "ids": {
            "itemId": item_id,
            "sourceTreeSha256": manifest["sourceTreeSha256"],
            "runtimeSha256": manifest["runtimeSha256"],
        },
        "inputs": {"itemId": item_id, "out": str(out)},
    }
    command_id = _append_studio_command(
        root,
        command="studio.project-export",
        status="passed",
        payload=payload,
        client=resolved_client,
        command_id=command_id,
        artifacts=artifacts,
    )
    _refresh_redaction_report(root)
    return StudioCommandResult("passed", root, payload, command_id)


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
    root = (
        Path(proof_root)
        if proof_root is not None
        else _default_out_dir(f"studio-run-{item_id}")
    )
    async with trace(f"studio-run-{item_id}", out=root):
        response = await Agent(environment=environment).run(prompt)
    context = response.execution_trace_context
    if context is None:
        raise AgentStudioWorkbenchError(
            "Agent run did not return executionTraceContext"
        )
    materialized_path = Path(response.execution_trace_path or root)
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
    run_path = materialized_path / "agent-studio" / "run.json"
    _write_json(run_path, run_report)
    artifacts = [
        _artifact_ref(materialized_path, run_path, "agent-studio-run"),
        _write_remote_item_ref(materialized_path, item, "remote-item"),
    ]
    materialization_report_path = (
        materialized_path / "reports" / "materialization-report.json"
    )
    materialization_report: dict[str, Any] = {}
    if materialization_report_path.exists():
        materialization_report = json.loads(
            materialization_report_path.read_text(encoding="utf-8")
        )
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
        "proofRoot": str(materialized_path),
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
        materialized_path,
        command="studio.run",
        status=payload["status"],
        payload=payload,
        client=resolved_client,
        artifacts=artifacts,
        warnings=["requires-active-client"],
    )
    _update_manifest_hash(
        materialized_path, "commandLedgerHash", materialized_path / "commands.jsonl"
    )
    _refresh_redaction_report(materialized_path)
    return StudioCommandResult(
        payload["status"], materialized_path, payload, command_id
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
        artifacts.append(_artifact_ref(root, cleanup_path, "cleanup"))
        artifacts.append(
            _write_remote_item_ref(root, item, "remote-item-before-delete")
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
    _refresh_redaction_report(root)
    return StudioCommandResult("passed", root, payload, command_id)

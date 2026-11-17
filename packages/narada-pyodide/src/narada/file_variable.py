from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, TypedDict, cast
from urllib.parse import quote

from narada_core.errors import NaradaError
from pyodide.http import pyfetch

from .utils import download_file as _download_file


class InMemoryFileVariableValue(TypedDict):
    source: Literal["inMemoryFile"]
    filename: str
    mimeType: str
    base64: str


class RemoteDispatchUploadFileVariableValue(TypedDict):
    source: Literal["remoteDispatchUpload"]
    id: str
    filename: str
    mimeType: str


class AgentStudioAttachmentFileVariableValue(TypedDict):
    source: Literal["agentStudioAttachment"]
    id: str
    filename: str
    mimeType: str
    itemId: str


type FileVariableValue = (
    InMemoryFileVariableValue
    | RemoteDispatchUploadFileVariableValue
    | AgentStudioAttachmentFileVariableValue
)


async def resolve_bytes(
    value: FileVariableValue,
    *,
    environment: Any | None = None,
    base_url: str | None = None,
    auth_headers: Mapping[str, str] | None = None,
) -> bytes:
    """Resolve a Narada file variable value to bytes."""
    if not isinstance(value, Mapping):
        raise TypeError(
            f"Expected a Narada file variable dict, got {type(value).__name__}"
        )

    source = _require_string(value, "source")
    if source == "inMemoryFile":
        return _decode_base64(_require_string(value, "base64"))

    resolved_base_url, resolved_auth_headers = await _resolve_api_connection(
        environment=environment,
        base_url=base_url,
        auth_headers=auth_headers,
    )
    if source == "remoteDispatchUpload":
        return await _resolve_remote_dispatch_upload(
            value,
            base_url=resolved_base_url,
            auth_headers=resolved_auth_headers,
        )
    if source == "agentStudioAttachment":
        return await _resolve_agent_studio_attachment(
            value,
            base_url=resolved_base_url,
            auth_headers=resolved_auth_headers,
        )

    raise ValueError(f"Unsupported file variable source: {source!r}")


async def download(
    value: FileVariableValue,
    *,
    filename: str | None = None,
    environment: Any | None = None,
    base_url: str | None = None,
    auth_headers: Mapping[str, str] | None = None,
) -> None:
    """Resolve a file variable value and trigger a browser download."""
    resolved_filename = filename or _get_download_filename(value)
    content = await resolve_bytes(
        value,
        environment=environment,
        base_url=base_url,
        auth_headers=auth_headers,
    )
    _download_file(resolved_filename, content)


def _get_download_filename(value: FileVariableValue) -> str:
    if not isinstance(value, Mapping):
        raise TypeError(
            f"Expected a Narada file variable dict, got {type(value).__name__}"
        )
    return _require_string(value, "filename")


async def _resolve_remote_dispatch_upload(
    value: Mapping[str, object],
    *,
    base_url: str,
    auth_headers: dict[str, str],
) -> bytes:
    response_data = await _post_json(
        f"{base_url}/remote-dispatch/generate-file-download-presigned-url",
        headers=auth_headers,
        payload={"id": _require_string(value, "id")},
    )
    return await _download_presigned_url(_require_string(response_data, "url"))


async def _resolve_agent_studio_attachment(
    value: Mapping[str, object],
    *,
    base_url: str,
    auth_headers: dict[str, str],
) -> bytes:
    file_id = _require_string(value, "id")
    item_id = _require_string(value, "itemId")
    encoded_item_id = quote(item_id, safe="")
    encoded_file_id = quote(file_id, safe="")
    response_data = await _get_json(
        f"{base_url}/agent-studio/items/{encoded_item_id}/attachments/{encoded_file_id}",
        headers=auth_headers,
    )
    return await _download_presigned_url(_require_string(response_data, "url"))


async def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, str],
) -> Mapping[str, object]:
    response = await pyfetch(
        url,
        method="POST",
        headers={**headers, "Content-Type": "application/json"},
        body=json.dumps(payload),
    )
    if not response.ok:
        raise NaradaError(
            "Failed to fetch remote-dispatch file download URL: "
            f"{response.status} {await response.text()}"
        )
    data = await response.json()
    if not isinstance(data, Mapping):
        raise NaradaError("Expected a JSON object from file download URL endpoint")
    return data


async def _get_json(url: str, *, headers: dict[str, str]) -> Mapping[str, object]:
    response = await pyfetch(url, headers=headers)
    if not response.ok:
        raise NaradaError(
            "Failed to fetch Agent Studio attachment download URL: "
            f"{response.status} {await response.text()}"
        )
    data = await response.json()
    if not isinstance(data, Mapping):
        raise NaradaError("Expected a JSON object from attachment download endpoint")
    return data


async def _download_presigned_url(url: str) -> bytes:
    response = await pyfetch(url)
    if not response.ok:
        raise NaradaError(
            f"Failed to download file contents: {response.status} {await response.text()}"
        )
    return bytes(await response.bytes())


async def _resolve_api_connection(
    *,
    environment: Any | None,
    base_url: str | None,
    auth_headers: Mapping[str, str] | None,
) -> tuple[str, dict[str, str]]:
    resolved_base_url = base_url
    resolved_auth_headers = dict(auth_headers) if auth_headers is not None else None

    if environment is not None:
        if resolved_base_url is None:
            environment_base_url = getattr(environment, "_base_url", None)
            if isinstance(environment_base_url, str):
                resolved_base_url = environment_base_url

        if resolved_auth_headers is None:
            get_auth_headers = cast(
                Callable[[], Awaitable[dict[str, str]]] | None,
                getattr(environment, "_get_auth_headers", None),
            )
            if callable(get_auth_headers):
                resolved_auth_headers = dict(await get_auth_headers())
            else:
                environment_auth_headers = getattr(environment, "_auth_headers", None)
                if isinstance(environment_auth_headers, Mapping):
                    resolved_auth_headers = dict(environment_auth_headers)

    if resolved_base_url is None:
        raise ValueError(
            "Resolving referenced file variables requires `environment` or `base_url`"
        )
    if resolved_auth_headers is None:
        raise ValueError(
            "Resolving referenced file variables requires `environment` or `auth_headers`"
        )
    return resolved_base_url.rstrip("/"), resolved_auth_headers


def _decode_base64(content: str) -> bytes:
    try:
        return base64.b64decode(content, validate=True)
    except binascii.Error as error:
        raise ValueError("Invalid base64 file content") from error


def _require_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"File variable value requires string field `{key}`")
    return item

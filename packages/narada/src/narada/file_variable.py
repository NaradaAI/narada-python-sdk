from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, TypedDict
from urllib.parse import quote

import aiohttp
from narada_core.errors import NaradaError


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
    """Resolve a Narada file variable value to bytes.

    Inline values are decoded locally. Agent Studio and remote-dispatch references are resolved
    through the existing authenticated API endpoints, then downloaded from the returned presigned URL.
    """
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
    output_path: str | os.PathLike[str],
    *,
    environment: Any | None = None,
    base_url: str | None = None,
    auth_headers: Mapping[str, str] | None = None,
) -> Path:
    """Resolve a file variable value and download it to a local path."""
    if isinstance(output_path, str) and not output_path:
        raise ValueError("output_path must not be empty")

    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        await resolve_bytes(
            value,
            environment=environment,
            base_url=base_url,
            auth_headers=auth_headers,
        )
    )
    return path


async def _resolve_remote_dispatch_upload(
    value: Mapping[str, object],
    *,
    base_url: str,
    auth_headers: dict[str, str],
) -> bytes:
    file_id = _require_string(value, "id")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base_url}/remote-dispatch/generate-file-download-presigned-url",
            headers=auth_headers,
            json={"id": file_id},
        ) as response:
            if not response.ok:
                raise NaradaError(
                    "Failed to fetch remote-dispatch file download URL: "
                    f"{response.status} {await response.text()}"
                )
            response_data = await response.json()
        return await _download_presigned_url(
            session, _require_string(response_data, "url")
        )


async def _resolve_agent_studio_attachment(
    value: Mapping[str, object],
    *,
    base_url: str,
    auth_headers: dict[str, str],
) -> bytes:
    file_id = _require_string(value, "id")
    encoded_file_id = quote(file_id, safe="")
    async with aiohttp.ClientSession() as session:
        item_id = _require_string(value, "itemId")
        encoded_item_id = quote(item_id, safe="")
        async with session.get(
            f"{base_url}/agent-studio/items/{encoded_item_id}/attachments/{encoded_file_id}",
            headers=auth_headers,
        ) as response:
            if not response.ok:
                raise NaradaError(
                    "Failed to fetch Agent Studio attachment download URL: "
                    f"{response.status} {await response.text()}"
                )
            response_data = await response.json()
        return await _download_presigned_url(
            session, _require_string(response_data, "url")
        )


async def _download_presigned_url(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url) as response:
        if not response.ok:
            raise NaradaError(
                f"Failed to download file contents: {response.status} {await response.text()}"
            )
        return await response.read()


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
            get_auth_headers = getattr(environment, "_get_auth_headers", None)
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

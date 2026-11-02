from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import narada.google_drive as google_drive_module
import pytest
from narada import Environment, GoogleDriveFile, InMemoryFileVariable, NaradaError
from narada_core.tracing.model import (
    DownloadGoogleDriveFileTrace,
    ForLoopTrace,
    ListGoogleDriveFilesTrace,
    parse_action_trace,
)
from pydantic import ValidationError

LISTED_FILE: GoogleDriveFile = {
    "id": "file-1",
    "name": "Report.pdf",
    "mimeType": "application/pdf",
    "url": "https://drive.google.com/file/d/file-1/view?resourcekey=file-key",
    "resourceKey": "file-key",
}
DOWNLOADED_FILE: InMemoryFileVariable = {
    "source": "inMemoryFile",
    "filename": "Report.pdf",
    "mimeType": "application/pdf",
    "base64": "JVBERi0=",
}


def _mock_session(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[dict[str, object]],
    *,
    status: int = 200,
) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    contexts = []
    for payload in responses:
        response = MagicMock()
        response.ok = status < 400
        response.status = status
        response.json = AsyncMock(return_value=payload)
        response.text = AsyncMock(return_value="File is not publicly shared")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        contexts.append(response)
    session.post.side_effect = contexts
    monkeypatch.setattr(google_drive_module.aiohttp, "ClientSession", lambda: session)
    return session


@pytest.mark.asyncio
async def test_drive_list_and_download_preserve_resource_key_without_browser_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _mock_session(
        monkeypatch, [{"files": [LISTED_FILE]}, dict(DOWNLOADED_FILE)]
    )
    env = Environment(
        api_key="narada-test-key", base_url="https://api.example.test/fast/v2"
    )

    files = await env.google_drive.list_files(
        folder="https://drive.google.com/drive/folders/folder-1"
    )
    downloaded = await env.google_drive.download_file(
        file=files[0], auth={"type": "public"}
    )

    assert files == [LISTED_FILE]
    assert downloaded == DOWNLOADED_FILE
    assert env._initialized is False
    assert session.post.call_args_list[0].args == (
        "https://api.example.test/fast/v2/google/drive/list-files",
    )
    assert session.post.call_args_list[0].kwargs == {
        "headers": {"x-api-key": "narada-test-key"},
        "json": {"folder": "https://drive.google.com/drive/folders/folder-1"},
    }
    assert session.post.call_args_list[1].args == (
        "https://api.example.test/fast/v2/google/drive/download-file",
    )
    assert session.post.call_args_list[1].kwargs["json"] == {
        "file": LISTED_FILE,
        "auth": {"type": "public"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference", ["file-1", "https://drive.google.com/file/d/file-1/view"]
)
async def test_drive_download_accepts_file_id_or_url(
    monkeypatch: pytest.MonkeyPatch, reference: str
) -> None:
    session = _mock_session(monkeypatch, [dict(DOWNLOADED_FILE)])
    env = Environment(api_key="test-key")

    assert await env.google_drive.download_file(file=reference) == DOWNLOADED_FILE
    assert session.post.call_args.kwargs["json"] == {"file": reference}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "download"])
async def test_drive_http_error_surfaces_to_caller(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    _mock_session(monkeypatch, [{}], status=403)
    env = Environment(api_key="test-key")

    with pytest.raises(NaradaError, match="Google Drive request failed: 403"):
        if operation == "list":
            await env.google_drive.list_files(folder="folder-1")
        else:
            await env.google_drive.download_file(file="file-1")


@pytest.mark.asyncio
async def test_drive_download_validates_file_variable_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_session(monkeypatch, [{"source": "inMemoryFile", "filename": "Report.pdf"}])
    env = Environment(api_key="test-key")

    with pytest.raises(ValidationError):
        await env.google_drive.download_file(file="file-1")


def test_drive_traces_parse_inside_for_loop() -> None:
    trace = parse_action_trace(
        [
            {"step_type": "listGoogleDriveFiles", "description": "Listed 1 file"},
            {
                "step_type": "for",
                "url": "",
                "loop_type": "forEachItemsInArray",
                "description": "For each file",
                "iterations": [
                    [
                        {
                            "step_type": "downloadGoogleDriveFile",
                            "description": "Downloaded Report.pdf",
                        }
                    ]
                ],
            },
        ]
    )

    assert isinstance(trace[0], ListGoogleDriveFilesTrace)
    assert isinstance(trace[1], ForLoopTrace)
    assert isinstance(trace[1].iterations[0][0], DownloadGoogleDriveFileTrace)

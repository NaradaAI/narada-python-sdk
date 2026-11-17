from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from narada import file_variable


class _FakeResponse:
    def __init__(
        self,
        *,
        payload: Any = None,
        body: bytes = b"",
        ok: bool = True,
        status: int = 200,
        text: str = "",
    ) -> None:
        self.ok = ok
        self.status = status
        self._payload = payload
        self._body = body
        self._text = text

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self) -> Any:
        return self._payload

    async def read(self) -> bytes:
        return self._body

    async def text(self) -> str:
        return self._text


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.post_calls.append({"url": url, **kwargs})
        return self._responses.pop(0)

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        return self._responses.pop(0)


class _FakeEnvironment:
    _base_url = "https://api.example.test/fast/v2"
    _auth_headers = {"x-api-key": "test-key"}


@pytest.mark.asyncio
async def test_in_memory_file_variable_resolves_and_downloads_to_path(
    tmp_path: Path,
) -> None:
    value = {
        "source": "inMemoryFile",
        "filename": "report.txt",
        "mimeType": "text/plain",
        "base64": "aGVsbG8=",
    }
    output_path = tmp_path / "nested" / "report.txt"

    assert await file_variable.resolve_bytes(value) == b"hello"
    assert await file_variable.download(value, output_path) == output_path
    assert output_path.read_bytes() == b"hello"


@pytest.mark.asyncio
async def test_non_file_variable_values_are_rejected() -> None:
    with pytest.raises(TypeError, match="Narada file variable dict"):
        await file_variable.resolve_bytes(b"raw file")


@pytest.mark.asyncio
async def test_remote_dispatch_upload_resolves_through_presigned_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        [
            _FakeResponse(payload={"url": "https://s3.example.test/report.txt"}),
            _FakeResponse(body=b"remote file"),
        ]
    )
    monkeypatch.setattr(
        file_variable.aiohttp,
        "ClientSession",
        lambda: session,
    )

    result = await file_variable.resolve_bytes(
        {
            "source": "remoteDispatchUpload",
            "id": "user-test/20260903000000000000-report.txt",
            "filename": "report.txt",
            "mimeType": "text/plain",
        },
        environment=_FakeEnvironment(),
    )

    assert result == b"remote file"
    assert session.post_calls == [
        {
            "url": "https://api.example.test/fast/v2/remote-dispatch/generate-file-download-presigned-url",
            "headers": {"x-api-key": "test-key"},
            "json": {"id": "user-test/20260903000000000000-report.txt"},
        }
    ]
    assert session.get_calls == [{"url": "https://s3.example.test/report.txt"}]


@pytest.mark.asyncio
async def test_agent_studio_attachment_resolves_with_item_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        [
            _FakeResponse(payload={"url": "https://s3.example.test/archive.zip"}),
            _FakeResponse(body=b"agent studio file"),
        ]
    )
    monkeypatch.setattr(
        file_variable.aiohttp,
        "ClientSession",
        lambda: session,
    )

    result = await file_variable.resolve_bytes(
        {
            "source": "agentStudioAttachment",
            "id": "file/with spaces.zip",
            "filename": "archive.zip",
            "mimeType": "application/zip",
            "itemId": "workflow/with spaces",
        },
        environment=_FakeEnvironment(),
    )

    assert result == b"agent studio file"
    assert session.get_calls == [
        {
            "url": "https://api.example.test/fast/v2/agent-studio/items/workflow%2Fwith%20spaces/attachments/file%2Fwith%20spaces.zip",
            "headers": {"x-api-key": "test-key"},
        },
        {"url": "https://s3.example.test/archive.zip"},
    ]


@pytest.mark.asyncio
async def test_agent_studio_attachment_requires_item_id() -> None:
    with pytest.raises(ValueError, match="itemId"):
        await file_variable.resolve_bytes(
            {
                "source": "agentStudioAttachment",
                "id": "file-1",
                "filename": "report.txt",
                "mimeType": "text/plain",
            },
            base_url="https://api.example.test/fast/v2",
            auth_headers={"x-api-key": "test-key"},
        )

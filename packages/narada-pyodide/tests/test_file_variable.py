from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PYODIDE_SRC = PROJECT_ROOT / "packages" / "narada-pyodide" / "src"
CORE_SRC = PROJECT_ROOT / "packages" / "narada-core" / "src"


class _FakeResponse:
    def __init__(
        self,
        *,
        ok: bool = True,
        status: int = 200,
        json_data: object | None = None,
        bytes_data: bytes = b"",
        text_data: str = "",
    ) -> None:
        self.ok = ok
        self.status = status
        self._json_data = json_data
        self._bytes_data = bytes_data
        self._text_data = text_data

    async def json(self) -> object | None:
        return self._json_data

    async def bytes(self) -> bytes:
        return self._bytes_data

    async def text(self) -> str:
        return self._text_data


class _FakeEnvironment:
    _base_url = "https://api.example.test/fast/v2"

    async def _get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer frontend-token"}


def _clear_modules() -> None:
    for name in list(sys.modules):
        if name == "narada" or name.startswith("narada."):
            sys.modules.pop(name, None)
    for name in ("js", "pyodide", "pyodide.http", "pyodide.ffi"):
        sys.modules.pop(name, None)


def _import_pyodide_file_variable(
    monkeypatch: pytest.MonkeyPatch, *, pyfetch: AsyncMock
):
    _clear_modules()
    monkeypatch.syspath_prepend(str(CORE_SRC))
    monkeypatch.syspath_prepend(str(PYODIDE_SRC))

    js_module = ModuleType("js")

    class _AbortController:
        @staticmethod
        def new() -> SimpleNamespace:
            return SimpleNamespace(signal=object(), abort=lambda: None)

    js_module.AbortController = _AbortController
    js_module.setTimeout = lambda callback, timeout: None

    pyodide_module = ModuleType("pyodide")
    pyodide_module.__path__ = []
    pyodide_http_module = ModuleType("pyodide.http")
    pyodide_http_module.pyfetch = pyfetch
    pyodide_ffi_module = ModuleType("pyodide.ffi")
    pyodide_ffi_module.JsProxy = object
    pyodide_ffi_module.create_once_callable = lambda fn: fn

    monkeypatch.setitem(sys.modules, "js", js_module)
    monkeypatch.setitem(sys.modules, "pyodide", pyodide_module)
    monkeypatch.setitem(sys.modules, "pyodide.http", pyodide_http_module)
    monkeypatch.setitem(sys.modules, "pyodide.ffi", pyodide_ffi_module)

    import importlib

    return importlib.import_module("narada.file_variable")


@pytest.mark.asyncio
async def test_remote_dispatch_upload_resolves_through_pyfetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"url": "https://s3.example.test/report.txt"}),
            _FakeResponse(bytes_data=b"remote file"),
        ]
    )
    file_variable = _import_pyodide_file_variable(monkeypatch, pyfetch=pyfetch)

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
    assert pyfetch.await_args_list[0].kwargs == {
        "method": "POST",
        "headers": {
            "Authorization": "Bearer frontend-token",
            "Content-Type": "application/json",
        },
        "body": '{"id": "user-test/20260903000000000000-report.txt"}',
    }
    assert pyfetch.await_args_list[0].args == (
        "https://api.example.test/fast/v2/remote-dispatch/generate-file-download-presigned-url",
    )
    assert pyfetch.await_args_list[1].args == ("https://s3.example.test/report.txt",)
    assert pyfetch.await_args_list[1].kwargs == {}


@pytest.mark.asyncio
async def test_agent_studio_attachment_resolves_with_item_id_in_pyodide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"url": "https://s3.example.test/archive.zip"}),
            _FakeResponse(bytes_data=b"agent studio file"),
        ]
    )
    file_variable = _import_pyodide_file_variable(monkeypatch, pyfetch=pyfetch)

    result = await file_variable.resolve_bytes(
        {
            "source": "agentStudioAttachment",
            "id": "file-1",
            "filename": "archive.zip",
            "mimeType": "application/zip",
            "itemId": "workflow-1",
        },
        environment=_FakeEnvironment(),
    )

    assert result == b"agent studio file"
    assert pyfetch.await_args_list[0].args == (
        "https://api.example.test/fast/v2/agent-studio/items/workflow-1/attachments/file-1",
    )
    assert pyfetch.await_args_list[0].kwargs == {
        "headers": {"Authorization": "Bearer frontend-token"},
    }
    assert pyfetch.await_args_list[1].args == ("https://s3.example.test/archive.zip",)
    assert pyfetch.await_args_list[1].kwargs == {}


@pytest.mark.asyncio
async def test_in_memory_file_variable_resolves_in_pyodide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_variable = _import_pyodide_file_variable(monkeypatch, pyfetch=AsyncMock())
    value = {
        "source": "inMemoryFile",
        "filename": "report.txt",
        "mimeType": "text/plain",
        "base64": "aGVsbG8=",
    }
    downloads: list[tuple[str, bytes]] = []
    monkeypatch.setattr(
        file_variable,
        "_download_file",
        lambda filename, content: downloads.append((filename, content)),
    )

    assert await file_variable.resolve_bytes(value) == b"hello"
    await file_variable.download(value)
    assert downloads == [("report.txt", b"hello")]


@pytest.mark.asyncio
async def test_non_file_variable_values_are_rejected_in_pyodide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_variable = _import_pyodide_file_variable(monkeypatch, pyfetch=AsyncMock())

    with pytest.raises(TypeError, match="Narada file variable dict"):
        await file_variable.resolve_bytes(b"raw file")

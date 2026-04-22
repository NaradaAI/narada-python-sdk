from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

PROJECT_ROOT = Path("/Users/zizheng/Projects/narada-python-sdk")
PYODIDE_SRC = PROJECT_ROOT / "packages" / "narada-pyodide" / "src"
CORE_SRC = PROJECT_ROOT / "packages" / "narada-core" / "src"


class _FakeResponse:
    def __init__(
        self,
        *,
        ok: bool = True,
        status: int = 200,
        json_data: object | None = None,
        text_data: str = "",
    ) -> None:
        self.ok = ok
        self.status = status
        self._json_data = json_data
        self._text_data = text_data

    async def json(self) -> object | None:
        return self._json_data

    async def text(self) -> str:
        return self._text_data


class _FakeJsProxy:
    def __init__(self, value: object):
        self._value = value

    def to_py(self) -> object:
        return self._value


def _clear_modules() -> None:
    for name in list(sys.modules):
        if name == "narada" or name.startswith("narada."):
            sys.modules.pop(name, None)
    for name in ("js", "pyodide", "pyodide.http", "pyodide.ffi"):
        sys.modules.pop(name, None)


def _import_pyodide_narada(monkeypatch: pytest.MonkeyPatch, *, pyfetch: AsyncMock):
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
    pyodide_ffi_module.JsProxy = _FakeJsProxy
    pyodide_ffi_module.create_once_callable = lambda fn: fn

    monkeypatch.setitem(sys.modules, "js", js_module)
    monkeypatch.setitem(sys.modules, "pyodide", pyodide_module)
    monkeypatch.setitem(sys.modules, "pyodide.http", pyodide_http_module)
    monkeypatch.setitem(sys.modules, "pyodide.ffi", pyodide_ffi_module)

    import importlib

    narada_pkg = importlib.import_module("narada")
    client_module = importlib.import_module("narada.client")
    window_module = importlib.import_module("narada.window")
    window_module._narada_parent_run_ids = _FakeJsProxy([])
    return narada_pkg, client_module, window_module


@pytest.mark.asyncio
async def test_open_and_initialize_cloud_browser_window_maps_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "session_id": "session-123",
                "session_name": "demo",
                "browser_window_id": "browser-window-123",
            }
        )
    )
    narada_pkg, _, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    client = narada_pkg.Narada(api_key="test-api-key")
    window = await client.open_and_initialize_cloud_browser_window(
        session_name="demo",
        session_timeout=321,
        require_extension=False,
    )

    assert isinstance(window, narada_pkg.CloudBrowserWindow)
    assert window.browser_window_id == "browser-window-123"
    assert window.cloud_browser_session_id == "session-123"

    call = pyfetch.await_args
    assert call is not None
    assert call.args[0].endswith(
        "/cloud-browser/create-and-initialize-cloud-browser-session"
    )
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "x-api-key": "test-api-key",
    }
    assert json.loads(call.kwargs["body"]) == {
        "session_name": "demo",
        "session_timeout": 321,
        "require_extension": False,
    }


@pytest.mark.asyncio
async def test_cloud_browser_window_close_stops_cloud_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(return_value=_FakeResponse(json_data={"success": True}))
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    await window.close()

    call = pyfetch.await_args
    assert call is not None
    assert call.args[0].endswith("/cloud-browser/stop-cloud-browser-session")
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["headers"] == {
        "x-api-key": "test-api-key",
        "Content-Type": "application/json",
    }
    assert json.loads(call.kwargs["body"]) == {"session_id": "session-123"}


@pytest.mark.asyncio
async def test_cloud_browser_window_get_downloaded_files_returns_presigned_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(
                json_data={
                    "downloaded_files": [
                        {
                            "file_name": "report.pdf",
                            "key": "downloads/session-123/report.pdf",
                            "size": 42,
                        }
                    ]
                }
            ),
            _FakeResponse(json_data={"presigned_url": "https://example.com/report.pdf"}),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    files = await window.get_downloaded_files()

    assert files == [
        window_module.SessionDownloadItem(
            file_name="report.pdf",
            size=42,
            download_url="https://example.com/report.pdf",
        )
    ]
    assert pyfetch.await_count == 2
    first_call, second_call = pyfetch.await_args_list
    assert "session_id=session-123" in first_call.args[0]
    assert first_call.args[0].endswith(
        "/cloud-browser/replay/downloads?session_id=session-123"
    )
    assert "session_id=session-123" in second_call.args[0]
    assert "key=downloads%2Fsession-123%2Freport.pdf" in second_call.args[0]


@pytest.mark.asyncio
async def test_remote_browser_window_without_cloud_session_keeps_extension_action_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(json_data={"status": "success", "data": None})
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.RemoteBrowserWindow(
        browser_window_id="browser-window-123",
        api_key="test-api-key",
    )
    await window.close()

    call = pyfetch.await_args
    assert call is not None
    assert call.args[0].endswith("/extension-actions")
    assert call.kwargs["method"] == "POST"
    payload = json.loads(call.kwargs["body"])
    assert payload["browserWindowId"] == "browser-window-123"
    assert payload["action"]["name"] == "close_window"

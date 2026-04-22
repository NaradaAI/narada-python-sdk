from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from packaging.version import InvalidVersion

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
    window_module._narada_get_id_token = AsyncMock(return_value="frontend-id-token")
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
async def test_open_and_initialize_cloud_browser_window_supports_frontend_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NARADA_API_KEY", raising=False)
    monkeypatch.setenv("NARADA_USER_ID", "user-123")
    monkeypatch.setenv("NARADA_ENV", "dev")

    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(
                json_data={
                    "packages": {"narada-pyodide": {"min_required_version": "0.0.1"}}
                }
            ),
            _FakeResponse(
                json_data={
                    "session_id": "session-456",
                    "session_name": "demo",
                    "browser_window_id": "browser-window-456",
                }
            ),
            _FakeResponse(json_data={"success": True}),
        ]
    )
    narada_pkg, _, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    async with narada_pkg.Narada() as client:
        window = await client.open_and_initialize_cloud_browser_window(
            session_name="demo",
            session_timeout=321,
            require_extension=True,
        )

    assert isinstance(window, narada_pkg.CloudBrowserWindow)
    assert window.browser_window_id == "browser-window-456"
    assert window.cloud_browser_session_id == "session-456"

    sdk_config_call, create_call = pyfetch.await_args_list
    assert sdk_config_call.args[0].endswith("/sdk/config")
    assert sdk_config_call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer frontend-id-token",
        "X-Narada-User-ID": "user-123",
        "X-Narada-Env": "dev",
    }
    assert create_call.args[0].endswith(
        "/cloud-browser/create-and-initialize-cloud-browser-session"
    )
    assert create_call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer frontend-id-token",
        "X-Narada-User-ID": "user-123",
        "X-Narada-Env": "dev",
    }

    await window.close()
    stop_call = pyfetch.await_args_list[-1]
    assert stop_call.args[0].endswith("/cloud-browser/stop-cloud-browser-session")
    assert stop_call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer frontend-id-token",
        "X-Narada-User-ID": "user-123",
        "X-Narada-Env": "dev",
    }


@pytest.mark.asyncio
async def test_open_and_initialize_cloud_browser_window_raises_when_version_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        return_value=_FakeResponse(
            json_data={
                "packages": {"narada-pyodide": {"min_required_version": "999.0.0"}}
            }
        )
    )
    narada_pkg, client_module, _ = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    monkeypatch.setattr(client_module, "__version__", "unknown")

    with pytest.raises(InvalidVersion) as exc_info:
        async with narada_pkg.Narada(api_key="test-api-key"):
            pass

    assert "Invalid version: 'unknown'" in str(exc_info.value)
    assert pyfetch.await_count == 1


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
async def test_cloud_browser_window_dispatch_request_omits_parent_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-123"}),
            _FakeResponse(json_data={"status": "success", "response": None}),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)
    window_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])

    window = window_module.CloudBrowserWindow(
        browser_window_id="browser-window-123",
        session_id="session-123",
        api_key="test-api-key",
    )
    response = await window.dispatch_request(prompt="hello from cloud browser")

    assert response["status"] == "success"
    post_call = pyfetch.await_args_list[0]
    assert post_call.args[0].endswith("/remote-dispatch")
    assert post_call.kwargs["method"] == "POST"
    payload = json.loads(post_call.kwargs["body"])
    assert payload["browserWindowId"] == "browser-window-123"
    assert payload["prompt"] == "/Operator hello from cloud browser"
    assert "parentRunIds" not in payload


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
            _FakeResponse(
                json_data={"presigned_url": "https://example.com/report.pdf"}
            ),
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
    window_module._narada_parent_run_ids = _FakeJsProxy(["outer-run", "inner-run"])

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
    assert "parentRunIds" not in payload


@pytest.mark.asyncio
async def test_local_browser_window_dispatch_request_uses_latest_parent_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARADA_API_KEY", "test-api-key")
    monkeypatch.setenv("NARADA_BROWSER_WINDOW_ID", "browser-window-123")
    pyfetch = AsyncMock(
        side_effect=[
            _FakeResponse(json_data={"requestId": "req-1"}),
            _FakeResponse(json_data={"status": "success", "response": None}),
            _FakeResponse(json_data={"requestId": "req-2"}),
            _FakeResponse(json_data={"status": "success", "response": None}),
        ]
    )
    _, _, window_module = _import_pyodide_narada(monkeypatch, pyfetch=pyfetch)

    window = window_module.LocalBrowserWindow()

    window_module._narada_parent_run_ids = _FakeJsProxy(["run-a"])
    first_response = await window.dispatch_request(prompt="first prompt")

    window_module._narada_parent_run_ids = _FakeJsProxy(["run-b", "run-c"])
    second_response = await window.dispatch_request(prompt="second prompt")

    assert first_response["status"] == "success"
    assert second_response["status"] == "success"

    first_post = json.loads(pyfetch.await_args_list[0].kwargs["body"])
    second_post = json.loads(pyfetch.await_args_list[2].kwargs["body"])
    assert first_post["parentRunIds"] == ["run-a"]
    assert second_post["parentRunIds"] == ["run-b", "run-c"]

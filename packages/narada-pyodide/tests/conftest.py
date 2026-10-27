from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PYODIDE_SRC = PROJECT_ROOT / "packages" / "narada-pyodide" / "src"
CORE_SRC = PROJECT_ROOT / "packages" / "narada-core" / "src"


class _AbortController:
    @staticmethod
    def new() -> SimpleNamespace:
        return SimpleNamespace(signal=object(), abort=lambda: None)


@pytest.fixture
def pyodide_narada(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Imports the Pyodide ``narada`` package instead of the desktop package that shares the
    workspace environment and module name.

    ``pyodide.http.pyfetch`` is an ``AsyncMock`` that tests configure through
    ``sys.modules["pyodide.http"].pyfetch``.
    """
    for name in list(sys.modules):
        if name == "narada" or name.startswith("narada."):
            sys.modules.pop(name)
    monkeypatch.syspath_prepend(str(CORE_SRC))
    monkeypatch.syspath_prepend(str(PYODIDE_SRC))

    js_module = ModuleType("js")
    js_module.AbortController = _AbortController
    js_module.setTimeout = lambda callback, timeout: None
    pyodide_module = ModuleType("pyodide")
    pyodide_module.__path__ = []
    pyodide_http_module = ModuleType("pyodide.http")
    pyodide_http_module.pyfetch = AsyncMock()
    pyodide_ffi_module = ModuleType("pyodide.ffi")
    pyodide_ffi_module.JsProxy = object
    pyodide_ffi_module.create_once_callable = lambda fn: fn
    monkeypatch.setitem(sys.modules, "js", js_module)
    monkeypatch.setitem(sys.modules, "pyodide", pyodide_module)
    monkeypatch.setitem(sys.modules, "pyodide.http", pyodide_http_module)
    monkeypatch.setitem(sys.modules, "pyodide.ffi", pyodide_ffi_module)

    narada = importlib.import_module("narada")
    assert Path(narada.__file__).is_relative_to(PYODIDE_SRC)
    return narada

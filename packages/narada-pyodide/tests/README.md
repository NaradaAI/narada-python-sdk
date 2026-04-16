# narada-pyodide tests

narada-pyodide and narada both publish under the top-level `narada` Python
package namespace. When both are installed in the same environment, the
workspace-installed `narada` package shadows narada-pyodide's source. This
is fine at runtime (Pyodide only installs narada-pyodide) but breaks
local unit testing.

To run the unit tests locally from the workspace root:

```bash
uv pip uninstall narada
uv run --package narada-pyodide pytest packages/narada-pyodide/tests/
```

Re-running `uv sync` will reinstall the `narada` package and require the
uninstall step again.

The `conftest.py` stubs the Pyodide-only `js` and `pyodide.*` imports so
the non-HTTP helpers in narada-pyodide can be exercised on host CPython.

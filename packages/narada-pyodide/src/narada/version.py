import importlib.metadata

try:
    __version__ = importlib.metadata.version("narada-pyodide")
except Exception:
    # Fallback sentinel. Validation treats this as a fatal release issue.
    __version__ = "unknown"

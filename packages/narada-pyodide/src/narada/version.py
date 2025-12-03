import importlib.metadata

try:
    __version__ = importlib.metadata.version("narada")
except Exception:
    # Fallback version if package metadata is not available
    __version__ = "unknown"

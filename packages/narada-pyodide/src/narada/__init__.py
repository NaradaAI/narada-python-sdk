import importlib.metadata

from narada_core.errors import (
    NaradaError,
    NaradaTimeoutError,
)
from narada_core.models import Agent, File, Response, ResponseContent

from narada.client import Narada
from narada.window import (
    LocalBrowserWindow,
    RemoteBrowserWindow,
)

# Get version from package metadata
try:
    __version__ = importlib.metadata.version("narada")
except Exception:
    # Fallback version if package metadata is not available
    __version__ = "unknown"

__all__ = [
    "__version__",
    "Agent",
    "File",
    "LocalBrowserWindow",
    "Narada",
    "NaradaError",
    "NaradaTimeoutError",
    "RemoteBrowserWindow",
    "Response",
    "ResponseContent",
]

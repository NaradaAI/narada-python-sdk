from importlib.metadata import version

from narada.client import Narada
from narada.config import BrowserConfig
from narada.window import LocalBrowserWindow, RemoteBrowserWindow
from narada_core.errors import (
    NaradaError,
    NaradaExtensionMissingError,
    NaradaExtensionUnauthenticatedError,
    NaradaInitializationError,
    NaradaTimeoutError,
    NaradaUnsupportedBrowserError,
)
from narada_core.models import Agent, File, Response, ResponseContent

# Get version from package metadata
try:
    __version__ = version("narada")
except Exception:
    # Fallback version if package metadata is not available
    __version__ = "unknown"

__all__ = [
    "Agent",
    "BrowserConfig",
    "File",
    "LocalBrowserWindow",
    "Narada",
    "NaradaError",
    "NaradaExtensionMissingError",
    "NaradaExtensionUnauthenticatedError",
    "NaradaInitializationError",
    "NaradaTimeoutError",
    "NaradaUnsupportedBrowserError",
    "RemoteBrowserWindow",
    "Response",
    "ResponseContent",
    "__version__",
]

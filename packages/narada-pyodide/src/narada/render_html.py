from typing import TYPE_CHECKING

from js import URL, Blob, Object  # type: ignore
from pyodide.ffi import to_js  # type: ignore

if TYPE_CHECKING:
    # Magic function injected by the JavaScript harness to open a new window.
    def _window_open(url: str, target: str | None = "_blank") -> None: ...


def render_html(html: str) -> None:
    """
    Renders HTML content by opening it in the default browser.

    Args:
        html: The HTML content to render.
    """
    options = to_js({"type": "text/html"}, dict_converter=Object.fromEntries)
    data = to_js([html])

    blob = Blob.new(data, options)
    url = URL.createObjectURL(blob)
    _window_open(url)
    URL.revokeObjectURL(url)

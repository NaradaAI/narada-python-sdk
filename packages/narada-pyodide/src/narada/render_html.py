from typing import TYPE_CHECKING
from js import Object, URL, Blob # type: ignore
from pyodide.ffi import to_js # type: ignore

if TYPE_CHECKING:
    # Magic function injected by the JavaScript harness to open a new window.
    def _window_open(url: str, target: str | None = '_blank') -> None: ...

def render_html(html: str) -> None:
    options = to_js({"type": "text/html"}, dict_converter=Object.fromEntries)
    data = to_js([html])

    blob = Blob.new(data, options)
    url = URL.createObjectURL(blob)
    _window_open(url)



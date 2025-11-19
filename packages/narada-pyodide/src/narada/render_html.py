import base64
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Magic function injected by the JavaScript harness to open a new window.
    def _window_open(url: str, target: str | None = "_blank") -> None: ...


def render_html(html: str) -> None:
    """
    Renders HTML content by opening it in the default browser.

    Args:
        html: The HTML content to render.
    """
    # Encode HTML to base64 for data URL
    html_bytes = html.encode("utf-8")
    html_base64 = base64.b64encode(html_bytes).decode("utf-8")
    # Create data URL
    data_url = f"data:text/html;base64,{html_base64}"

    _window_open(data_url)

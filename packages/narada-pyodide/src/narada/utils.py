from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Magic functions injected by the JavaScript harness.
    def _narada_render_html(html: str) -> None: ...
    def _narada_download_file(filename: str, content: str | bytes) -> None: ...


def download_file(filename: str, content: str | bytes) -> None:
    """
    Downloads a file to the user's device.

    Args:
        filename: The name of the file to save.
        content: The content to write. If str, writes in text mode (UTF-8). If
                 bytes, writes in binary mode.
    """
    _narada_download_file(filename, content)


def render_html(html: str) -> None:
    """
    Renders HTML content by opening it in the default browser.

    Args:
        html: The HTML content to render.
    """
    _narada_render_html(html)

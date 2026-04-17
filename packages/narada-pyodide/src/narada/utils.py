from typing import TYPE_CHECKING

from . import _trace

if TYPE_CHECKING:
    # Magic functions injected by the JavaScript harness.
    def _narada_render_html(html: str) -> None: ...
    def _narada_download_file(filename: str, content: str | bytes) -> None: ...


def download_file(filename: str, content: str | bytes) -> None:
    """
    Downloads a file to the user's Downloads directory.

    Args:
        filename: The name of the file to save. Can include subdirectories
                  (e.g., "reports/2025/data.csv") relative to the Downloads
                  directory.
        content: The content to write. If str, writes in text mode (UTF-8).
                 If bytes, writes in binary mode.
    """
    try:
        _narada_download_file(filename, content)
    except Exception as err:
        # Record that the attempt happened and failed, then re-raise so user
        # code still sees the exception.
        _trace.emit_side_effect(
            effect_type="download_file",
            description=f"Failed to download file {filename}: {err}",
        )
        raise
    _trace.emit_side_effect(
        effect_type="download_file",
        description=f"Downloaded file: {filename}",
    )


def render_html(html: str) -> None:
    """
    Renders HTML content by opening it in the default browser.

    Args:
        html: The HTML content to render.
    """
    try:
        _narada_render_html(html)
    except Exception as err:
        _trace.emit_side_effect(
            effect_type="render_html",
            description=f"Failed to render HTML: {err}",
        )
        raise
    _trace.emit_side_effect(
        effect_type="render_html",
        description="Rendered HTML in a new tab",
    )

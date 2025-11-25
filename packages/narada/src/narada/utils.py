import webbrowser
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Never


def assert_never() -> Never:
    raise AssertionError("Expected code to be unreachable")


def download_file(filename: str, content: str | bytes) -> None:
    """
    Downloads a file to the user's Downloads directory.

    Args:
        filename: The name of the file to save.
        content: The content to write. If str, writes in text mode (UTF-8). If
                 bytes, writes in binary mode.
    """
    path = Path.home() / "Downloads" / filename
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


def render_html(html: str) -> None:
    """
    Renders HTML content by opening it in the default browser.

    Args:
        html: The HTML content to render.
    """
    with NamedTemporaryFile(
        mode="w+t",
        encoding="utf-8",
        suffix=".html",
        delete=False,
    ) as temp:
        temp.write(html)
        path = temp.name

    webbrowser.open_new_tab(f"file://{path}")

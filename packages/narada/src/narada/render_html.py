import webbrowser
from tempfile import NamedTemporaryFile


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

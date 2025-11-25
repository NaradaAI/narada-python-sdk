from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Magic function injected by the JavaScript harness to render HTML in a new tab.
    def _narada_render_html(html: str) -> None: ...


def render_html(html: str) -> None:
    """
    Renders HTML content by opening it in the default browser.

    Args:
        html: The HTML content to render.
    """
    _narada_render_html(html)

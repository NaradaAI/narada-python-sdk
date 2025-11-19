import base64
import webbrowser


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
    webbrowser.open_new_tab(data_url)

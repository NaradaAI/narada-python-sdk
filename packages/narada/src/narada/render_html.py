import webbrowser


def render_html(html: str) -> None:
    """
    Renders HTML content by opening it in the default browser.

    Args:
        html: The HTML content to render.
    """
    data_url = f"data:text/html;charset=utf-8,{html}"
    webbrowser.open_new_tab(data_url)

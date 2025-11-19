import base64
import webbrowser

def render_html(html: str) -> None:
    """
    Renders HTML content by opening it in the default browser.
    
    Creates a data URL from the HTML content and opens it in a new browser window/tab.
    
    Args:
        html: The HTML content to render as a string.
    """
    # Encode HTML to base64 for data URL
    html_bytes = html.encode('utf-8')
    html_base64 = base64.b64encode(html_bytes).decode('utf-8')
    # Create data URL
    data_url = f"data:text/html;base64,{html_base64}"
    webbrowser.open(data_url, new=2)  # new=2 opens in a new tab if possible

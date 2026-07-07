from narada import render_html


def main() -> None:
    html = """
<html>
    <body>
        <h1>Hello, World!</h1>
        <p>This is a paragraph.</p>
        <ul>
            <li>Item 1</li>
            <li>Item 2</li>
            <li>Item 3</li>
        </ul>
        <table>
            <tr>
                <th>Name</th>
                <th>Age</th>
                <th>City</th>
            </tr>
            <tr>
                <td>John</td>
                <td>25</td>
                <td>New York</td>
            </tr>
            <tr>
                <td>Jane</td>
                <td>30</td>
                <td>Los Angeles</td>
            </tr>
        </table>
    </body>
</html>
"""
    render_html(html)


if __name__ == "__main__":
    main()

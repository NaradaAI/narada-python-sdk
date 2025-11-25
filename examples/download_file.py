from pathlib import Path

from narada import download_file


def load_demo_image() -> bytes:
    image_path = Path(__file__).parent / "demo_image.png"
    return image_path.read_bytes()


def main() -> None:
    # Example 1: Download a text file (CSV)
    csv_content = """name,age,city
John,25,New York
Jane,30,Los Angeles
Bob,35,Chicago
Alice,28,San Francisco
"""
    download_file("example_people.csv", csv_content)

    # Example 2: Download a binary file (PNG image)
    binary_content = load_demo_image()
    download_file("example_image.png", binary_content)

    print("Files downloaded to your Downloads directory.")


if __name__ == "__main__":
    main()

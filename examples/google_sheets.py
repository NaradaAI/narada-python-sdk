import asyncio

from narada import Narada


async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        resp = await window.read_google_sheet(
            spreadsheet_id="REPLACE_WITH_YOUR_OWN",
            range="Sheet1!A1:D10",
        )
        print(resp.values)

        await window.write_google_sheet(
            spreadsheet_id="REPLACE_WITH_YOUR_OWN",
            range="Sheet1!A11:D12",
            values=[["hello", "world", "foo", "bar"], ["1", "2", "3", "4"]],
        )


if __name__ == "__main__":
    asyncio.run(main())

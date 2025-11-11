import asyncio

from narada import Narada


async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        # Read from a public Google Sheet.
        resp = await window.read_google_sheet(
            spreadsheet_id="1COnQZsoxb_eMKWscX3e5OuFk-xQAHWza9QN2Tw0H6sg",
            range="Sheet1!A1:D10",
        )
        print(resp.values)

        # To write to a Google Sheet, you need to have write permission to the sheet. You can copy
        # the spreadsheet ID from the URL of the sheet, which looks like:
        # https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/...
        #
        # await window.write_google_sheet(
        #     spreadsheet_id="SPREADSHEET_ID",
        #     range="Sheet1!A11:D12",
        #     values=[["hello", "world", "foo", "bar"], ["1", "2", "3", "4"]],
        # )


if __name__ == "__main__":
    asyncio.run(main())

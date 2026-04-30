import asyncio

from narada import Narada


async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        # To read from an Excel workbook, connect the Microsoft account that has access
        # to the workbook and use the workbook URL from Excel Online.
        resp = await window.read_excel_sheet(
            workbook_url="https://contoso.sharepoint.com/:x:/r/sites/Team/Shared%20Documents/Workbook.xlsx",
            range="Sheet1!A1:D10",
            microsoft_account_email="person@example.com",
        )
        print(resp.values)

        # To write to an Excel workbook, you need to have write permission to the workbook.
        # You can copy the workbook URL from Excel Online.
        #
        # await window.write_excel_sheet(
        #     workbook_url="WORKBOOK_URL",
        #     range="Sheet1!A11:D12",
        #     microsoft_account_email="person@example.com",
        #     values=[["hello", "world", "foo", "bar"], ["1", "2", "3", "4"]],
        # )


if __name__ == "__main__":
    asyncio.run(main())

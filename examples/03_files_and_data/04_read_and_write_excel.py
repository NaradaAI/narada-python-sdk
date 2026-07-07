import asyncio

from narada import Agent, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env)

    try:
        # To read from an Excel workbook, connect the Microsoft account that has access
        # to the workbook and use the workbook URL from Excel Online.
        resp = await agent.read_excel_sheet(
            workbook_url="https://contoso.sharepoint.com/:x:/r/sites/Team/Shared%20Documents/Workbook.xlsx",
            range="Sheet1!A1:D10",
            microsoft_account_email="person@example.com",
        )
        print(resp.values)

        # To write to an Excel workbook, you need to have write permission to the workbook.
        # You can copy the workbook URL from Excel Online.
        #
        # await agent.write_excel_sheet(
        #     workbook_url="WORKBOOK_URL",
        #     range="Sheet1!A11:D12",
        #     microsoft_account_email="person@example.com",
        #     values=[["hello", "world", "foo", "bar"], ["1", "2", "3", "4"]],
        # )
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

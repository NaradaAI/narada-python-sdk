import asyncio

from narada import Agent, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env)

    try:
        # Read from a public Google Sheet.
        resp = await agent.read_google_sheet(
            spreadsheet_id="1COnQZsoxb_eMKWscX3e5OuFk-xQAHWza9QN2Tw0H6sg",
            range="Sheet1!A1:D10",
        )
        print(resp.values)

        # To write to a Google Sheet, you need to have write permission to the sheet. You can copy
        # the spreadsheet ID from the URL of the sheet, which looks like:
        # https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/...
        #
        # await agent.write_google_sheet(
        #     spreadsheet_id="SPREADSHEET_ID",
        #     range="Sheet1!A11:D12",
        #     values=[["hello", "world", "foo", "bar"], ["1", "2", "3", "4"]],
        # )
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

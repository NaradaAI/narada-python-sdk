import asyncio

from narada import RemoteBrowserWindow


async def main() -> None:
    # The browser window ID uniquely identifies a browser window anywhere in the world. Assuming we
    # have already launched a browser window on another machine and obtained its ID by visiting
    # https://app.narada.ai/initialize.
    browser_window_id = "REPLACE_WITH_BROWSER_WINDOW_ID"

    window = RemoteBrowserWindow(browser_window_id=browser_window_id)

    # Run a task on another machine.
    response = await window.agent(
        prompt=(
            'Search for "LLM Compiler" on Google and open the first arXiv paper on the results '
            "page, then tell me who the authors are."
        )
    )

    print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

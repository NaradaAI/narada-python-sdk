import asyncio

from narada import RemoteBrowserWindow


async def main() -> None:
    # The browser window ID uniquely identifies a browser window anywhere in the world. Assuming we
    # have already launched a browser window on another machine and obtained its ID by visiting
    # https://app.narada.ai/initialize.
    browser_window_id = "REPLACE_WITH_BROWSER_WINDOW_ID"

    # Optional: If the window was launched as a cloud browser session, provide its session ID to
    # enable additional management capabilities such as stopping the session:
    #
    # ```
    # win_1 = await narada.open_and_initialize_cloud_browser_window(...)
    #
    # browser_window_id = win_1.browser_window_id
    # cloud_browser_session_id = win_1.cloud_browser_session_id
    #
    # ...
    #
    # win_2 = RemoteBrowserWindow(
    #     browser_window_id=browser_window_id,
    #     loud_browser_session_id=cloud_browser_session_id,
    # )
    # await win_2.close()  # This will stop the cloud session.
    # ```
    cloud_browser_session_id = None

    window = RemoteBrowserWindow(
        browser_window_id=browser_window_id,
        cloud_browser_session_id=cloud_browser_session_id,
    )

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

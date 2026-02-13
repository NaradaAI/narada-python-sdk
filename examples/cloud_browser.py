import asyncio

from narada import Narada
from narada.window import RemoteBrowserWindow


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a cloud browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_cloud_browser_window(
            session_name="my-cloud-browser-session",  # Optional: label the session
            session_timeout=3600,  # Optional: session timeout in seconds
        )

        # Run a task in this browser window.
        response = await window.agent(
            prompt=(
                'Search for "LLM Compiler" on Google and open the first arXiv paper on the results '
                "page, then tell me who the authors are."
            )
        )

        print("Response:", response.model_dump_json(indent=2))

    # The cloud session is still running after exiting the context manager.
    # You can save the session ID for later reconnection or management.
    cloud_browser_session_id = window.cloud_browser_session_id
    browser_window_id = window.browser_window_id

    # Change these to test the different options below.
    stop_session_now = False

    # The cloud session runs independently. If you want to stop it after the task is
    # complete, you can explicitly close it. The session will also auto-expire after the
    # configured session_timeout.
    if stop_session_now:
        print(
            f"Stopping cloud session {cloud_browser_session_id} through original window"
        )
        await window.close()
    else:
        # Create a `RemoteBrowserWindow` instance with the session ID to manage the session later.
        print(
            f"Stopping cloud session {cloud_browser_session_id} through RemoteBrowserWindow"
        )
        remote_window = RemoteBrowserWindow(
            cloud_browser_session_id=cloud_browser_session_id,
            browser_window_id=browser_window_id,
        )
        await remote_window.close()  # This will stop the cloud session.

    ############################################################################
    # IMPORTANT: The cloud browser continues accruing costs until the session  #
    # is stopped or times out. To avoid unexpected costs, make sure to stop    #
    # the session when you're done.                                            #
    ############################################################################


if __name__ == "__main__":
    asyncio.run(main())

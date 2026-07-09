import asyncio

from narada import Agent, CloudBrowserEnvironment, RemoteBrowserEnvironment


async def main() -> None:
    # Create a cloud browser environment. It initializes lazily on the first action.
    env = CloudBrowserEnvironment(
        session_name="my-cloud-browser-session",  # Optional: label the session
        session_timeout=3600,  # Optional: session timeout in seconds
    )
    agent = Agent(environment=env)

    cloud_browser_session_id = None
    browser_window_id = None

    try:
        # Run a task in this cloud browser.
        response = await agent.run(
            prompt=(
                'Search for "LLM Compiler" on Google and open the first arXiv paper on the results '
                "page, then tell me who the authors are."
            )
        )

        print("Response:", response.model_dump_json(indent=2))

        # The cloud session keeps running until explicitly stopped or it times out.
        # Save these IDs for later reconnection or management.
        cloud_browser_session_id = env.cloud_browser_session_id
        browser_window_id = env.browser_window_id

        # Get files downloaded during the session.
        downloaded_files = await env.get_downloaded_files()
        print(f"Downloaded files {downloaded_files}")

    finally:
        # Change this to test stopping through the original environment versus
        # reconnecting with a remote environment.
        stop_session_through_original_environment = False

        if cloud_browser_session_id is None or browser_window_id is None:
            await env.close()
        elif stop_session_through_original_environment:
            print(f"Stopping cloud session {cloud_browser_session_id}")
            await env.close()
        else:
            # Create a RemoteBrowserEnvironment with the session ID to manage the session later.
            print(
                f"Stopping cloud session {cloud_browser_session_id} through RemoteBrowserEnvironment"
            )
            remote_env = RemoteBrowserEnvironment(
                cloud_browser_session_id=cloud_browser_session_id,
                browser_window_id=browser_window_id,
            )
            await remote_env.close()  # This will stop the cloud session.

    ############################################################################
    # IMPORTANT: The cloud browser continues accruing costs until the session  #
    # is stopped or times out. To avoid unexpected costs, make sure to stop    #
    # the session when you're done.                                            #
    ############################################################################


if __name__ == "__main__":
    asyncio.run(main())

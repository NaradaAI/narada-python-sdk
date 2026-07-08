import asyncio

from narada import Agent, RemoteBrowserEnvironment


async def main() -> None:
    # The browser window ID uniquely identifies a browser window anywhere in the world. Assuming we
    # have already launched a browser window on another machine and obtained its ID by visiting
    # https://app.narada.ai/initialize.
    browser_window_id = "REPLACE_WITH_BROWSER_WINDOW_ID"

    # Optional: If the window was launched as a cloud browser session, provide its session ID to
    # enable additional management capabilities such as stopping the session:
    #
    # ```
    # cloud_env = CloudBrowserEnvironment(...)
    # await cloud_env.start()
    #
    # browser_window_id = cloud_env.browser_window_id
    # cloud_browser_session_id = cloud_env.cloud_browser_session_id
    #
    # ...
    #
    # remote_env = RemoteBrowserEnvironment(
    #     browser_window_id=browser_window_id,
    #     cloud_browser_session_id=cloud_browser_session_id,
    # )
    # await remote_env.close()  # This will stop the cloud session.
    # ```
    cloud_browser_session_id = None

    env = RemoteBrowserEnvironment(
        browser_window_id=browser_window_id,
        cloud_browser_session_id=cloud_browser_session_id,
    )
    agent = Agent(environment=env)

    # Run a task on another machine.
    response = await agent.run(
        prompt=(
            'Search for "LLM Compiler" on Google and open the first arXiv paper on the results '
            "page, then tell me who the authors are."
        )
    )

    print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

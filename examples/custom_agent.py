import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Run a custom agent, optionally setting the $userQuery system variable for that agent.
        #
        # The definition of this demo agent can be viewed at:
        # https://app.narada.ai/agent-builder/agents/demo%2540narada.ai%3Agreeter-agent
        custom_agent = "/demo@narada.ai/greeter-agent"
        user_query = "John Doe"
        response = await window.dispatch_request(
            prompt=user_query,
            agent=custom_agent,
        )

        assert response["response"] is not None
        print("Response:", response["response"]["text"])


if __name__ == "__main__":
    asyncio.run(main())

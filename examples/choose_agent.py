import asyncio

from narada import Agent, Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Choose a specific agent to handle the task. By default, the Operator agent is used.
        response = await window.dispatch_request(
            prompt="Tell me a joke.", agent=Agent.GENERALIST
        )

        assert response["response"] is not None
        print("Response:", response["response"]["text"])


if __name__ == "__main__":
    asyncio.run(main())

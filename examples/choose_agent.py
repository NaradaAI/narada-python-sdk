import asyncio

from narada import Agent, Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Choose a specific agent to handle the task. By default, the Operator agent is used.
        response = await window.agent(prompt="Tell me a joke.", agent=Agent.GENERALIST)

        print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

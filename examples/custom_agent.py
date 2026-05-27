import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Run a custom agent with a prompt (mapped to `chat_input` server-side).
        #
        # The definition of this demo agent can be viewed at:
        # https://app.narada.ai/agent-studio/agents/e9d8vb8Q7bD2AcaSkqmRZ
        custom_agent = "/demo@narada.ai/greeter-agent"
        chat_input = "John Doe"
        response = await window.agent(
            prompt=chat_input,
            agent=custom_agent,
        )

        print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

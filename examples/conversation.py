import asyncio

from narada import Agent, Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        resp = await window.agent(
            prompt="Pick a lucky number for me between 1 and 100",
            agent=Agent.GENERALIST,
            # By default, the chat history is cleared when an agent is invoked so that the agent can
            # start fresh.
            clear_chat=True,
        )
        print(resp.text)

        resp = await window.agent(
            prompt="What did you pick again?",
            agent=Agent.GENERALIST,
            # By not clearing the chat history, we can continue the conversation.
            clear_chat=False,
        )
        print(resp.text)

        resp = await window.agent(
            prompt="What's double that number?",
            agent=Agent.GENERALIST,
            # By not clearing the chat history, we can continue the conversation.
            clear_chat=False,
        )
        print(resp.text)


if __name__ == "__main__":
    asyncio.run(main())

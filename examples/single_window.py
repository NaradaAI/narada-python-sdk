import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Run a task in this browser window.
        response = await window.agent(
            prompt='Search for "LLM Compiler" on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.',
            # Optionally generate a GIF of the agent's actions.
            generate_gif=True,
        )

        print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

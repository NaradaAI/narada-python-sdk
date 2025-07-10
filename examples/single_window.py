import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Run a task in this browser window.
        response = await window.dispatch_request(
            prompt='/Operator Search for "LLM Compiler" on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.',
            # Optionally generate a GIF of the agent's actions.
            generate_gif=True,
        )

        assert response["response"] is not None
        print("Response:", response["response"]["text"])


if __name__ == "__main__":
    asyncio.run(main())

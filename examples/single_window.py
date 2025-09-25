import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Run a task in this browser window.
        response = await window.agent(
            prompt="Search for ${paper_name} on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.",
            # Optionally generate a GIF of the agent's actions.
            generate_gif=True,
            # Put sensitive information that you don't want the LLM to see in variables. These will
            # be substituted at action time after the LLM has generated its output.
            variables={"paper_name": "LLM Compiler"},
        )

        print("Response:", response.model_dump_json(indent=2))

    # The browser runs as an independent process. If you want to close it after the task is
    # complete, you can get its process ID from the window object.
    pid = window.browser_process_id
    # Process ID is only available if it was originally launched by Narada.
    if pid is not None:
        print(f"Browser process ID: {pid}")
        # os.kill(pid, signal.SIGTERM)


if __name__ == "__main__":
    asyncio.run(main())

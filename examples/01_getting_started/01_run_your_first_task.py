import asyncio
import os
import signal

from narada import Agent, BrowserEnvironment


async def main() -> None:
    # Create a browser environment. It initializes lazily on the first action.
    env = BrowserEnvironment()
    agent = Agent(environment=env)

    # Run a task in this browser environment.
    response = await agent.run(
        prompt="Search for ${paper_name} on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.",
        # Optionally generate a GIF of the agent's actions.
        generate_gif=True,
        # Put sensitive information that you don't want the LLM to see in secret_variables.
        # These will
        # be substituted at action time after the LLM has generated its output.
        secret_variables={"paper_name": "LLM Compiler"},
    )

    print("Response:", response.model_dump_json(indent=2))

    # Change these to test the different options below.
    should_quit_browser = False
    should_close_window = False

    # The browser runs as an independent process. If you want to close it after the task is
    # complete, you can get its process ID from the environment object.
    pid = env.browser_process_id
    # Process ID is only available if it was originally launched by Narada.
    if pid is not None and should_quit_browser:
        print("Killing browser process with PID:", pid)
        os.kill(pid, signal.SIGTERM)

    # You can also close this specific window instead of quitting the entire browser process.
    if should_close_window:
        print("Closing window...")
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

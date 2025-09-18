import asyncio
import subprocess
import sys

from narada import Narada
from narada.config import BrowserConfig


async def launch_browser(config: BrowserConfig) -> None:
    browser_args = [
        f"--user-data-dir={config.user_data_dir}",
        f"--profile-directory={config.profile_directory}",
        f"--remote-debugging-port={config.cdp_port}",
        "--no-default-browser-check",
        "--no-first-run",
    ]

    # Launch an independent browser process which will not be killed when the current program exits.
    if sys.platform == "win32":
        subprocess.Popen(
            [config.executable_path, *browser_args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS,
        )
    else:
        await asyncio.create_subprocess_exec(
            config.executable_path,
            *browser_args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )


async def main() -> None:
    config = BrowserConfig()

    # Step 1: Launch browser outside of Narada SDK. In practice, the browser can be launched in any
    # way, as long as CDP is enabled.
    print(f"Launching browser with CDP port {config.cdp_port}...")
    await launch_browser(config)

    # Wait a bit for the browser to be ready.
    await asyncio.sleep(5)

    # Step 2: Use Narada SDK to attach to the existing browser.
    print("Connecting to existing browser with Narada SDK...")
    async with Narada() as narada:
        # Attach to the existing browser window.
        window = await narada.initialize_in_existing_browser_window(config)

        print(f"Successfully attached to browser window: {window.browser_window_id}")

        # Run a task in this browser window
        response = await window.agent(
            prompt='Search for "LLM Compiler" on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.',
            # Optionally generate a GIF of the agent's actions
            generate_gif=True,
        )

        print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

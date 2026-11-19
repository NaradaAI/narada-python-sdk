import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

from narada import Agent, BrowserConfig, BrowserEnvironment


async def main() -> None:
    api_base_url = os.environ["NARADA_API_BASE_URL"]
    if urlsplit(api_base_url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("This example requires a local NARADA_API_BASE_URL.")

    config = BrowserConfig(
        initialization_url="http://localhost:3000/initialize",
        extension_id=os.environ["NARADA_EXTENSION_ID"],
        unpacked_extension_path=os.environ["NARADA_UNPACKED_EXTENSION_PATH"],
    )
    config.executable_path = os.getenv(
        "NARADA_BROWSER_EXECUTABLE_PATH", config.executable_path
    )
    config.user_data_dir = os.getenv(
        "NARADA_BROWSER_USER_DATA_DIR", config.user_data_dir
    )
    config.cdp_port = int(os.getenv("NARADA_BROWSER_CDP_PORT", str(config.cdp_port)))

    env = BrowserEnvironment(config=config)
    agent = Agent(environment=env)
    html_path = Path(__file__).with_name("demo_serve_html.html")

    try:
        with html_path.open("rb") as file:
            await agent.serve_html(file=file)

        print(f"Served {html_path.name} at {(await agent.get_url()).url}")
        response = await agent.run(
            prompt="On the current page, click Increment counter once and report its value."
        )
        print("Operator response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

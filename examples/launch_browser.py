import asyncio

from narada import Narada
from narada.config import BrowserConfig


async def main() -> None:
    narada = Narada()
    config = BrowserConfig(
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    session = await narada.launch_browser_and_initialize(config)
    print("Narada session ID:", session.id)


if __name__ == "__main__":
    asyncio.run(main())

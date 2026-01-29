import asyncio

from narada import Narada
from narada_core.actions.models import parse_action_trace


async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        await window.go_to_url(url="https://www.google.com", timeout=60)
        current_url = await window.get_url(timeout=30)
        print(f"Current URL: {current_url}")


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os

from narada import Narada


async def main() -> None:
    async with Narada() as narada:
        window = await narada.create_managed_browser()

        print(f"Managed browser session created successfully! Browser Window ID: {window.browser_window_id}")

        # Run a task in this browser window
        response = await window.agent(
            prompt=(
                'Search for "LLM Compiler" on Google and open the first arXiv paper on the results '
                "page, then tell me who the authors are."
            )
        )

        print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

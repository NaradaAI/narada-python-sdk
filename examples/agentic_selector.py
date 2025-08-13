import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        await window.go_to_url(url="https://www.google.com")

        await window.agentic_selector(
            action={"type": "click"},
            selectors={
                # Change this to something else to see the fallback Operator query in action.
                "aria_label": "Search for Images ",
            },
            fallback_operator_query='click on "Images" near the top of the page',
        )


if __name__ == "__main__":
    asyncio.run(main())

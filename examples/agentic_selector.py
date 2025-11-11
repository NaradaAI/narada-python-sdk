import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        await window.go_to_url(url="https://www.google.com")

        await window.agentic_selector(
            action={"type": "fill", "value": "Narada AI"},
            selectors={
                "tag_name": "textarea",
                "name": "q",
            },
            fallback_operator_query='type "Narada AI" in the search box',
        )

        await window.agentic_selector(
            action={"type": "click"},
            selectors={
                "xpath": "/html/body/div[2]/div[4]/form/div[1]/div[1]/div[2]/div[4]/div[6]/center/input[1]",
            },
            fallback_operator_query="click on the Google Search button",
        )


if __name__ == "__main__":
    asyncio.run(main())

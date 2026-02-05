import asyncio

from narada import Narada


async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        await window.go_to_url(url="https://www.google.com")
        await window.agentic_mouse_action(
            action={"type": "click"},
            recorded_click={
                "x": 500,
                "y": 300,
                "viewport": {
                    "width": 1280,
                    "height": 720,
                },
            },
            fallback_operator_query="click on the search box",
        )

        await window.agentic_mouse_action(
            action={"type": "fill", "text": "Narada AI", "press_enter": False},
            recorded_click={
                "x": 500,
                "y": 300,
                "viewport": {
                    "width": 1280,
                    "height": 720,
                },
            },
            fallback_operator_query='type "Narada AI" in the search box',
        )

        await window.agentic_mouse_action(
            action={"type": "scroll", "horizontal": 0, "vertical": 500},
            recorded_click={
                "x": 640,
                "y": 360,
                "viewport": {
                    "width": 1280,
                    "height": 720,
                },
            },
            fallback_operator_query="scroll down the page",
        )


if __name__ == "__main__":
    asyncio.run(main())

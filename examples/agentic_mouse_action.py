import asyncio

from narada import Agent, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env)

    try:
        await agent.go_to_url(url="https://www.google.com")
        await agent.agentic_mouse_action(
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

        await agent.agentic_mouse_action(
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

        await agent.agentic_mouse_action(
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
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

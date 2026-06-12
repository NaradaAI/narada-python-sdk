import asyncio

from narada import Agent, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env)

    try:
        await agent.go_to_url(
            url="https://w3c.github.io/uievents/tools/key-event-viewer.html", timeout=60
        )

        # Dict items are accepted (same shape as JSON); PressKeyEventItem is optional.
        await agent.press_key(
            events=[
                {"type": "keyDown", "code": "KeyA", "key": "a"},
                {"type": "keyUp", "code": "KeyA", "key": "a"},
            ],
        )

        await agent.press_key(
            events=[
                {
                    "type": "keyDown",
                    "code": "ShiftLeft",
                    "key": "Shift",
                    "modifiers": {"shift": True},
                },
                {
                    "type": "keyDown",
                    "code": "KeyA",
                    "key": "A",
                    "modifiers": {"shift": True},
                },
                {
                    "type": "keyUp",
                    "code": "KeyA",
                    "key": "A",
                    "modifiers": {"shift": True},
                },
                {"type": "keyUp", "code": "ShiftLeft", "key": "Shift"},
            ],
        )
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

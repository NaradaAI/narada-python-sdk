import asyncio

from narada import Narada


async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        await window.go_to_url(
            url="https://w3c.github.io/uievents/tools/key-event-viewer.html", timeout=60
        )

        # Dict items are accepted (same shape as JSON); PressKeyEventItem is optional.
        await window.press_key(
            events=[
                {"type": "keyDown", "code": "KeyA", "key": "a"},
                {"type": "keyUp", "code": "KeyA", "key": "a"},
            ],
        )

        await window.press_key(
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


if __name__ == "__main__":
    asyncio.run(main())

import asyncio

from narada import Narada

async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        await window.go_to_url(url="https://app.narada.ai", timeout=60)
        property_response = await window.agentic_selector(
            action={"type": "get_property", "property_name": "className"},
            selectors={"data_testid": "create-new-agent-button"},
            fallback_operator_query="get className from create button",
            timeout=60,
        )
        print(f"Class Name: {property_response['value']}")

        print("\nTest 2: Getting text content...")
        text_response = await window.agentic_selector(
            action={"type": "get_text"},
            selectors={"data_testid": "create-new-agent-button"},
            fallback_operator_query="get text from create button",
            timeout=60,
        )
        print(f"Text: {text_response['value']}")


if __name__ == "__main__":
    asyncio.run(main())

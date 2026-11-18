import asyncio
import os

from narada import Agent, BrowserConfig, BrowserEnvironment


async def main() -> None:
    config = BrowserConfig()
    config.initialization_url = os.getenv(
        "NARADA_INITIALIZATION_URL", config.initialization_url
    )
    config.extension_id = os.getenv("NARADA_EXTENSION_ID", config.extension_id)
    config.executable_path = os.getenv(
        "NARADA_BROWSER_EXECUTABLE_PATH", config.executable_path
    )
    config.user_data_dir = os.getenv(
        "NARADA_BROWSER_USER_DATA_DIR", config.user_data_dir
    )
    config.cdp_port = int(os.getenv("NARADA_BROWSER_CDP_PORT", str(config.cdp_port)))
    config.unpacked_extension_path = os.getenv("NARADA_UNPACKED_EXTENSION_PATH")
    env = BrowserEnvironment(config=config)
    agent = Agent(environment=env)

    try:
        await agent.go_to_url(url="https://books.toscrape.com/", timeout=60)

        books = await agent.get_matching_elements(
            selector="article.product_pod h3 a",
            timeout=30,
        )

        print(f"Found {len(books)} books on this page:")
        for book in books:
            print(f"{book['text']}: {book['url']}")
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

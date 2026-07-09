import asyncio

from narada import Agent, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env)

    try:
        await agent.go_to_url(url="https://www.google.com", timeout=60)
        result = await agent.get_url(timeout=30)
        print(f"Current URL: {result.url}")
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

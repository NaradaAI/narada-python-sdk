import asyncio

from narada import Agent, AgentKind, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind=AgentKind.CORE_AGENT)

    try:
        resp = await agent.run(
            prompt="Pick a lucky number for me between 1 and 100",
        )
        print(resp.text)

        resp = await agent.run(
            prompt="What did you pick again?",
            # Pass the previous request ID to continue from the earlier response.
            previous_request_id=resp.request_id,
        )
        print(resp.text)

        resp = await agent.run(
            prompt="What's double that number?",
            previous_request_id=resp.request_id,
        )
        print(resp.text)
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

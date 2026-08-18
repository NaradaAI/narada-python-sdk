import asyncio
import json

from narada import Agent, AgentKind, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind=AgentKind.OPERATOR)

    try:
        response = await agent.run(
            prompt=(
                "Open https://example.com and tell me the page heading and current URL."
            )
        )

        print("Response:", response.text)
        print("Trace:")
        print(
            json.dumps(
                [record.model_dump(mode="json") for record in response.trace],
                indent=2,
            )
        )
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import json

from narada import Agent, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind="/demo@narada.ai/greeter-agent")

    try:
        response = await agent.run(prompt="John Doe")

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

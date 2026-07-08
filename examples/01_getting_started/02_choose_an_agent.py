import asyncio

from narada import Agent, AgentKind, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind=AgentKind.CORE_AGENT)

    try:
        # Choose a specific agent to handle the task. By default, the Operator agent is used.
        response = await agent.run(prompt="Tell me a joke.")

        print("Response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

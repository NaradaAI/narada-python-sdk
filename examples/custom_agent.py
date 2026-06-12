import asyncio

from narada import Agent, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()

    # Run a custom agent with a prompt (mapped to `chat_input` server-side).
    #
    # The definition of this demo agent can be viewed at:
    # https://app.narada.ai/agent-studio/agents/e9d8vb8Q7bD2AcaSkqmRZ
    custom_agent = "/demo@narada.ai/greeter-agent"
    agent = Agent(environment=env, kind=custom_agent)
    chat_input = "John Doe"

    try:
        response = await agent.run(prompt=chat_input)

        print("Response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

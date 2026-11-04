import asyncio

from narada import Agent, BrowserEnvironment, Guardrails


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind="/demo@narada.ai/greeter-agent")
    try:
        response = await agent.run(
            "John Doe",
            guardrails=Guardrails(
                url_allowlist=["https://example.com/*"],
                url_blacklist=["https://example.com/private/*"],
            ),
        )
        print("Response:", response.model_dump_json(indent=2))
        # Guardrails() clears both lists for this call. Omit the argument to use saved settings.
        # This configuration does not enforce navigation yet.
        response = await agent.run("Jane Doe", guardrails=Guardrails())
        print("Response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

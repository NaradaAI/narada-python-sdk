import asyncio

from narada import Agent, BrowserEnvironment, Guardrails


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind="/demo@narada.ai/greeter-agent")
    try:
        # Override the workflow's saved URL guardrails with an allowlist for this run only.
        # Specify either url_allowlist or url_blocklist, not both.
        response = await agent.run(
            "John Doe",
            guardrails=Guardrails(url_allowlist=["https://example.com/*"]),
        )
        print("Response:", response.model_dump_json(indent=2))
        # Or override with a blocklist instead:
        response = await agent.run(
            "Alex Doe",
            guardrails=Guardrails(url_blocklist=["https://example.com/private/*"]),
        )
        print("Response:", response.model_dump_json(indent=2))
        # Override the workflow's saved URL guardrails with no restrictions
        # for this run only. The saved workflow settings stay unchanged.
        # Leave out the guardrails argument to use the workflow's saved guardrails.
        response = await agent.run("Jane Doe", guardrails=Guardrails())
        print("Response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

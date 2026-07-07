import asyncio

from narada import Agent, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env)

    try:
        await agent.go_to_url(url="https://www.google.com")

        await agent.agentic_selector(
            action={"type": "fill", "value": "Narada AI"},
            selectors={
                "tag_name": "textarea",
                "name": "q",
            },
            fallback_operator_query='type "Narada AI" in the search box',
        )

        await agent.agentic_selector(
            action={"type": "click"},
            selectors={
                "xpath": "/html/body/div[2]/div[4]/form/div[1]/div[1]/div[2]/div[4]/div[6]/center/input[1]",
            },
            fallback_operator_query="click on the Google Search button",
        )
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

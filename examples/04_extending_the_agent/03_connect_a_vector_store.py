import asyncio

from narada import Agent, AgentKind, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()

    try:
        vector_store = await env.vector_stores.get(
            path="/owner@example.com/Knowledge/Product documentation"
        )
        response = await Agent(
            environment=env,
            kind=AgentKind.PRODUCTIVITY,
        ).run(
            prompt=(
                "Answer from the attached knowledge base and cite the source filenames."
            ),
            vector_stores=[vector_store],
        )

        print(response.text)
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

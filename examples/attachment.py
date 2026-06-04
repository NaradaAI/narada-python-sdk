import asyncio
from pathlib import Path

from narada import Agent, AgentKind, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind=AgentKind.CORE_AGENT)

    try:
        # Pass a file-like object as an attachment. The SDK uploads it automatically
        # before dispatching the request.
        current_dir = Path(__file__).parent
        with open(current_dir / "demo_attachment_file.txt", "rb") as f:
            response = await agent.run(
                prompt="Summarize the attached file.",
                attachment=f,
            )

        print("Response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

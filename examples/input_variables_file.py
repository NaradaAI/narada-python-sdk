import asyncio
from io import BytesIO

from narada import Agent, AgentKind, BrowserEnvironment


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind=AgentKind.CORE_AGENT)

    try:
        # Create an in-memory file object and pass it in input_variables.
        # The SDK uploads it automatically before dispatching the request.
        file_obj = BytesIO(
            b"This is a sample document for input_variables file upload."
        )
        file_obj.name = "sample_document.txt"

        response = await agent.run(
            prompt="Summarize {{$doc}}.",
            input_variables={"doc": file_obj},
        )

        print("Response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import json

from narada import Agent, BrowserEnvironment
from narada_core.tracing import Span


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
        root = next(
            (
                record
                for record in response.trace
                if isinstance(record, Span) and record.parent_id is None
            ),
            None,
        )
        print("Request credits:", response.usage.credits)
        print(
            "Root inclusive trace credits:",
            getattr(getattr(root, "span_data", None), "credits", None),
        )
        print("Inclusive credits must not be summed across the trace tree.")
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

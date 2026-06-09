import asyncio

from narada import Agent, BrowserEnvironment


async def main() -> None:
    # Helper function to run a task in a new browser environment.
    async def run_task(prompt: str):
        env = BrowserEnvironment()
        agent = Agent(environment=env)
        try:
            return await agent.run(prompt=prompt)
        finally:
            await env.close()

    # Run multiple tasks in parallel.
    responses = await asyncio.gather(
        run_task(
            "Search for Kurt Keutzer on Google and extract his h-index which you can find by clicking on cited by tab in google scholar"
        ),
        run_task(
            'Search for "LLM Compiler" on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.'
        ),
        run_task(
            'Search for "random number" on Google and extract the generated number from the search result page'
        ),
    )

    for i, response in enumerate(responses):
        print(f"Response #{i + 1}: {response.model_dump_json(indent=2)}\n")


if __name__ == "__main__":
    asyncio.run(main())

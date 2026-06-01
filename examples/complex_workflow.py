import asyncio

from narada import Agent, AgentKind, BrowserEnvironment
from pydantic import BaseModel


class PaperInfo(BaseModel):
    title: str
    url: str


class Papers(BaseModel):
    papers: list[PaperInfo]


async def main() -> None:
    env = BrowserEnvironment()
    core_agent = Agent(environment=env, kind=AgentKind.CORE_AGENT)
    operator = Agent(environment=env)

    try:
        await core_agent.go_to_url(url="https://arxiv.org/list/cs.AI/recent")

        resp = await core_agent.run(
            prompt="What are the top 2 AI papers based on the current page?",
            output_schema=Papers,
        )

        papers = resp.structured_output
        assert papers is not None

        print("Top 2 AI papers:", papers.model_dump_json(indent=2))

        for paper in papers.papers:
            await operator.go_to_url(url=paper.url)
            await operator.run(prompt="Click 'View PDF' then download the PDF")

        await operator.print_message(message="All done!")
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

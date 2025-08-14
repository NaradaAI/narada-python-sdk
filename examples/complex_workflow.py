import asyncio

from pydantic import BaseModel

from narada import Narada, Agent


class PaperInfo(BaseModel):
    title: str
    url: str


class Papers(BaseModel):
    papers: list[PaperInfo]


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        await window.go_to_url(url="https://arxiv.org/list/cs.AI/recent")

        resp = await window.agent(
            prompt="What are the top 3 AI papers based on the current page?",
            agent=Agent.GENERALIST,
            output_schema=Papers,
        )

        papers = resp.structured_output
        assert papers is not None

        print("Top 3 AI papers:", papers.model_dump_json(indent=2))

        for paper in papers.papers:
            await window.go_to_url(url=paper.url)
            await window.agent(prompt="Click 'View PDF' then download the PDF")

        await window.print_message(message="All done!")


if __name__ == "__main__":
    asyncio.run(main())

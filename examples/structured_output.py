import asyncio

import rich
from pydantic import BaseModel, Field

from narada import Narada


class PaperInfo(BaseModel):
    title: str = Field(description="The title of the paper")
    authors: list[str] = Field(description="The authors of the paper")
    version: int = Field(description="The current version of the paper")
    pdf_url: str = Field(description="The URL of the PDF of the paper")
    comments: str = Field(
        description="The 'Comments' field about the paper in its arXiv page"
    )
    subjects: str = Field(
        description="The 'Subjects' field about the paper in its arXiv page"
    )


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Run a task in this browser window.
        response = await window.dispatch_request(
            prompt=(
                '/Operator Search for "LLM Compiler" on Google and open the first arXiv paper on '
                "the results page. Then extract the paper info from the arXiv page in the given "
                "format."
            ),
            output_schema=PaperInfo,
        )

        assert response["response"] is not None
        rich.print("Response:", response["response"]["structuredOutput"])


if __name__ == "__main__":
    asyncio.run(main())

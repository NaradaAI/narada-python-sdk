import asyncio

from narada import Narada
from pydantic import BaseModel


class PaperAuthor(BaseModel):
    name: str


class ScholarInfo(BaseModel):
    h_index: int


async def main() -> None:
    # In this example, we use two browser windows to perform two tasks in parallel.
    #
    # Step 1: Get the first author's name for a paper from window 1.

    # Step 2: In parallel,
    #   - In window 1, fill in the author's name in Google Contacts.
    #   - In window 2, search for the author's h-index in Google Scholar.
    #
    # Step 3: In window 1, add a note with the h-index information.

    async with Narada() as narada:
        window_1, window_2 = await asyncio.gather(
            narada.open_and_initialize_browser_window(),
            narada.open_and_initialize_browser_window(),
        )

        # First, get the author's name from window 1
        response = await window_1.agent(
            prompt=(
                'Search for "LLM Compiler" on Google and open the first arXiv paper on the results '
                "page, then extract the first author's name from the arXiv page."
            ),
            output_schema=PaperAuthor,
        )
        assert response.structured_output is not None
        author_name = response.structured_output.name
        print(f"First author is {author_name}")

        # Start parallel tasks: name filling in window 1, h-index search in window 2
        async def fill_name_in_contact() -> None:
            await window_1.go_to_url(url="https://contacts.google.com/new")
            await window_1.agent(
                prompt=(
                    f"Fill in the first name and last name fields for {author_name}. Do not save."
                )
            )

        async def search_h_index() -> int:
            response = await window_2.agent(
                prompt=(
                    f"Search for {author_name} with Google and extract their h-index, which you "
                    "can find by opening their Google Scholar profile and clicking on the CITED BY "
                    "tab."
                ),
                output_schema=ScholarInfo,
            )
            assert response.structured_output is not None
            return response.structured_output.h_index

        # Run both tasks in parallel.
        print("Running h-index search and name filling in parallel...")
        _, h_index = await asyncio.gather(
            fill_name_in_contact(),
            search_h_index(),
        )

        # Now add a note with h-index information.
        print("Adding h-index note to contact...")
        await window_1.agent(
            prompt=(f"Add a note that their h-index is {h_index}. Do not click save."),
        )


if __name__ == "__main__":
    asyncio.run(main())

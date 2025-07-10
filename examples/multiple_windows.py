import asyncio

from narada import Narada, Response


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Helper function to run a task in a new browser window.
        async def run_task(prompt: str) -> Response:
            window = await narada.open_and_initialize_browser_window()
            return await window.dispatch_request(prompt=prompt)

        # Run multiple tasks in parallel.
        responses = await asyncio.gather(
            run_task(
                "/Operator Search for Kurt Keutzer on Google and extract his h-index which you can find by clicking on cited by tab in google scholar"
            ),
            run_task(
                '/Operator Search for "LLM Compiler" on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.'
            ),
            run_task(
                '/Operator Search for "random number" on Google and extract the generated number from the search result page'
            ),
        )

        for i, response in enumerate(responses):
            assert response["response"] is not None
            print(f"Response {i + 1}: {response['response']['text']}\n")


if __name__ == "__main__":
    asyncio.run(main())

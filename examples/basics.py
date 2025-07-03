import asyncio

from narada import Narada
from narada.config import BrowserConfig


async def main() -> None:
    narada = Narada()
    config = BrowserConfig(initialization_url="http://localhost:3000/initialize")

    prompts = [
        "/Operator Search for Amir Gholami on LinkedIn, open his profile page and summarize his background",
        "/Operator Find the LLM Compiler paper on arXiv and open its PDF",
        "Search for Kurt Keutzer on Google and extract his h-index",
    ]

    async def run_task(prompt: str) -> str:
        window = await narada.open_and_initialize_browser_window(config)
        response = await window.dispatch_request(prompt=prompt)
        return response["response"]["text"]

    responses = await asyncio.gather(*[run_task(prompt) for prompt in prompts])

    for i, response in enumerate(responses):
        print(f"Response {i + 1}:", response)
        print()


if __name__ == "__main__":
    asyncio.run(main())

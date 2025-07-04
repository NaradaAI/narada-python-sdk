import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Run a task in this browser window.
        response = await window.dispatch_request(
            prompt='/Operator Search for "random number between 1 and 5" on Google and extract the generated number from the search result page. Output just the number.',
        )
        print(f"Response 1: {response['response']['text']}\n")

        # Run a second task based on the first task's result.
        response = await window.dispatch_request(
            prompt=f"/Operator search for the number {response['response']['text']} tallest building in the world on Google",
        )
        print(f"Response 2: {response['response']['text']}\n")


if __name__ == "__main__":
    asyncio.run(main())

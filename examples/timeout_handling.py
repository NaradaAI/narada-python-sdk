import asyncio

from narada import Narada, NaradaTimeoutError


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = await window.dispatch_request(
                    prompt='/Operator Search for "random number between 1 and 5" on Google and extract the generated number from the search result page. Output just the number.',
                    # Force a timeout on the first attempt to demonstrate timeout handling.
                    timeout=3 if attempt == 0 else 120,
                )

                assert response["response"] is not None
                print("Response:", response["response"]["text"])
            except NaradaTimeoutError:
                # Give up after `max_attempts` attempts.
                if attempt == max_attempts - 1:
                    raise

                print("Request timed out, retrying...")

                # Reinitialize the UI agent to cancel any inflight requests. This keeps the browser
                # pages untouched so we don't lose any progress.
                await window.reinitialize()


if __name__ == "__main__":
    asyncio.run(main())

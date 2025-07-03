import asyncio

from narada import Narada


async def main() -> None:
    narada = Narada()

    window = await narada.open_and_initialize_browser_window()

    response = await window.dispatch_request(
        prompt='/Operator Search for "random number" on Google and extract the generated number from the search result page'
    )

    print(response["response"]["text"])


if __name__ == "__main__":
    asyncio.run(main())

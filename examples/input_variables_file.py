import asyncio
from io import BytesIO

from narada import Agent, Narada


async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        # Create an in-memory file object and pass it in input_variables.
        # The SDK uploads it automatically before dispatching the request.
        file_obj = BytesIO(
            b"This is a sample document for input_variables file upload."
        )
        file_obj.name = "sample_document.txt"

        response = await window.agent(
            prompt="Summarize {{$doc}}.",
            agent=Agent.CORE_AGENT,
            input_variables={"doc": file_obj},
        )

        print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

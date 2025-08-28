import asyncio

from narada import Agent, Narada


async def main() -> None:
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        # Upload a file to be later used as an attachment.
        with open("/Users/johndoe/quote.pdf", "rb") as f:
            file = await window.upload_file(file=f)

        # Ask the agent to use the attachment.
        response = await window.agent(
            prompt="Summarize the attached file.",
            agent=Agent.GENERALIST,
            attachment=file,
        )

        print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

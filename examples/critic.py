import asyncio

from narada import Narada, CriticConfig
from pydantic import BaseModel, Field


class SearchCriticOutput(BaseModel):
    search_query_used: str = Field(description="The exact search query the agent used")
    result_count: int = Field(description="The number of results the agent found")


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        window = await narada.open_and_initialize_browser_window()

        # Define a critic that verifies the agent completed the task and extracts
        # additional structured information from the agent's actions.
        critic = CriticConfig(
            prompt=(
                "Verify that the agent successfully searched Google and found results. "
                "Extract the exact search query the agent used and the number of results found."
            ),
            output_schema=SearchCriticOutput,
        )

        # Run a task with the critic. After the main agent finishes, the critic
        # evaluates whether the task was completed successfully.
        response = await window.agent(
            prompt='Search Google for "Narada AI" and tell me how many results were found.',
            critic=critic,
        )

        print("Agent response:", response.text)
        print("Critic result:", response.critic_result.validation_passed)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio

from narada import Agent, AgentKind, BrowserEnvironment, UserAbortedError
from narada_core.actions.models import PromptForUserInputVariable


async def main() -> None:
    # Use a browser environment where Narada can show the human-in-the-loop UI.
    env = BrowserEnvironment()
    agent = Agent(environment=env, kind=AgentKind.CORE_AGENT)

    try:
        # Use prompt_for_user_input when the script needs runtime details
        # that should come from a person instead of being hard-coded.
        values = await agent.prompt_for_user_input(
            step_id="collect-research-details",
            variables=[
                PromptForUserInputVariable(
                    name="company",
                    type="string",
                    required=True,
                ),
                PromptForUserInputVariable(
                    name="research_focus",
                    type="enum",
                    required=True,
                    enum_values=["pricing", "customers", "recent news"],
                ),
            ],
            prompt_message="Tell us which company to research and what to focus on.",
        )

        company = values["company"]
        research_focus = values["research_focus"]

        # Use user_approval before an action that costs time, uses credits,
        # changes external state, or depends on the user's confirmation.
        approved = await agent.user_approval(
            step_id="approve-research-run",
            prompt_message=f"Research {company} with a focus on {research_focus}?",
            approve_label="Run research",
            reject_label="Cancel",
        )

        if not approved:
            print("The user rejected the research run.")
            return

        # The agent only runs after the user has supplied the missing
        # details and approved the proposed action.
        response = await agent.run(
            prompt=(
                f"Research {company}. Focus on {research_focus}. "
                "Return a concise summary with the most relevant findings."
            ),
        )

        print("Response:", response.model_dump_json(indent=2))

    except UserAbortedError:
        # The user can also close/cancel a human-in-the-loop prompt.
        print("The user cancelled the human-in-the-loop flow.")
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

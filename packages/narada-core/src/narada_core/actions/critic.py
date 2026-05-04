from __future__ import annotations

from typing import Any, Awaitable, Callable

from narada_core.models import Agent, CriticConfig
from pydantic import BaseModel, create_model

from narada_core.actions.models import AgentUsage, CriticResult, parse_action_trace

_VALIDATION_VAR = "narada_validation_passed"
_DEFAULT_CRITIC_PROMPT = (
    "Using your context about the actions and outcome of the previous agent, "
    "determine whether its task was completed successfully."
)


async def run_critic(
    *,
    dispatch_request: Callable[..., Awaitable[Any]],
    original_prompt: str,
    response_content: dict[str, Any],
    action_trace_raw: list[Any] | None,
    critic: CriticConfig,
    time_zone: str,
    timeout: int,
) -> CriticResult:
    output_schema = critic.get("output_schema")
    if output_schema is not None:
        combined_fields: dict[str, Any] = {
            name: (info.annotation, info)
            for name, info in output_schema.model_fields.items()
        }
    else:
        combined_fields = {}
    combined_fields[_VALIDATION_VAR] = (bool, ...)
    CriticOutputModel = create_model("CriticOutput", **combined_fields)

    critic_dispatch_response = await dispatch_request(
        prompt=critic.get("prompt", _DEFAULT_CRITIC_PROMPT),
        agent=Agent.PRODUCTIVITY,
        output_schema=CriticOutputModel,
        critic_context={
            "agentPrompt": original_prompt,
            "agentOutput": response_content["text"],
            "actionTrace": action_trace_raw or [],
            "validationVariableName": _VALIDATION_VAR,
        },
        mcp_servers=critic.get("mcp_servers"),
        time_zone=time_zone,
        timeout=timeout,
    )

    critic_content = critic_dispatch_response["response"]
    if critic_content is None:
        raise ValueError("Critic dispatch returned no response")

    combined_output = critic_content.get("structuredOutput")
    validation_passed = (
        bool(getattr(combined_output, _VALIDATION_VAR, False))
        if combined_output is not None
        else False
    )

    structured_output: BaseModel | None = None
    if output_schema is not None and combined_output is not None:
        output_dict = combined_output.model_dump()
        output_dict.pop(_VALIDATION_VAR, None)
        structured_output = output_schema.model_validate(output_dict)

    critic_action_trace_raw = critic_content.get("actionTrace")
    critic_action_trace = (
        parse_action_trace(critic_action_trace_raw)
        if critic_action_trace_raw is not None
        else None
    )

    return CriticResult(
        validation_passed=validation_passed,
        text=critic_content["text"],
        structured_output=structured_output,
        usage=AgentUsage.model_validate(critic_dispatch_response["usage"]),
        action_trace=critic_action_trace,
    )

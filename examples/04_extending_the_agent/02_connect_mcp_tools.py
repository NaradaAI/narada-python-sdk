import asyncio

from narada import Agent, BrowserEnvironment
from narada_core.models import (
    AuthenticationNone,
    McpServer,
)


async def main() -> None:
    env = BrowserEnvironment()
    agent = Agent(environment=env)

    try:
        # Define an MCP server configuration.
        # This example uses no authentication, but you can also use:
        # - AuthenticationBearerToken(bearerToken="your-token")
        # - AuthenticationCustomHeaders(customHeaders=[CustomHeader(key="X-API-Key", value="your-key")])
        mcp_server = McpServer(
            url="https://your-mcp-server.example.com",
            label="My MCP Server",
            description="A custom MCP server for specialized tools",
            authentication=AuthenticationNone(),
            # Optionally specify which tools to use from this MCP server by the tool name.
            # If not specified, all available tools will be used.
            selectedTools=["tool_name_1", "tool_name_2"],
        )

        # Run a task with the MCP server linked to the agent.
        # The agent will have access to the tools from the specified MCP server.
        response = await agent.run(
            prompt="Use the MCP server tools to fetch and process some data",
            mcp_servers=[mcp_server],
        )

        print("Response:", response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio

from narada import Narada
from narada_core.models import AuthenticationType, McpServer


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Define an MCP server configuration.
        # This example uses no authentication, but you can also use:
        # - AuthenticationType.BEARER_TOKEN: {"type": AuthenticationType.BEARER_TOKEN, "bearerToken": "your-token"}
        # - AuthenticationType.CUSTOM_HEADERS: {"type": AuthenticationType.CUSTOM_HEADERS, "customHeaders": [{"key": "X-API-Key", "value": "your-key"}]}
        mcp_server: McpServer = {
            "url": "https://your-mcp-server.example.com",
            "label": "My MCP Server",
            "description": "A custom MCP server for specialized tools",
            "authentication": {"type": AuthenticationType.NONE},
            # Optionally specify which tools to use from this MCP server by the tool name.
            # If not specified, all available tools will be used.
            "selectedTools": ["tool_name_1", "tool_name_2"],
        }

        # Run a task with the MCP server linked to the agent.
        # The agent will have access to the tools from the specified MCP server.
        response = await window.agent(
            prompt="Use the MCP server tools to fetch and process some data",
            mcp_servers=[mcp_server],
        )

        print("Response:", response.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

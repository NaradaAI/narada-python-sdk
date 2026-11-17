import asyncio
import os

from narada import Agent, BrowserConfig, CloudBrowserEnvironment, ProxyConfig


async def main() -> None:
    # The SDK sends proxy credentials over the authenticated Narada API. Caddie
    # stores them in a temporary AWS Secrets Manager secret for AgentCore startup.
    proxy = ProxyConfig(
        server=os.environ["NARADA_PROXY_SERVER"],
        username=os.getenv("NARADA_PROXY_USERNAME"),
        password=os.getenv("NARADA_PROXY_PASSWORD"),
        bypass=os.getenv("NARADA_PROXY_BYPASS"),
    )
    env = CloudBrowserEnvironment(config=BrowserConfig(proxy=proxy))
    agent = Agent(environment=env)

    try:
        response = await agent.run(
            prompt="Go to https://httpbin.org/ip and tell me what IP address is shown."
        )
        print("Response:", response.text)
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

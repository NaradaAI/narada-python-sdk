import asyncio
import os

from narada import Agent, BrowserConfig, CloudBrowserEnvironment, ProxyConfig


async def main() -> None:
    # For an authenticated proxy, store username/password JSON under
    # narada-cloud-browser-proxy/<organization_id>/ in the backend AWS account.
    proxy = ProxyConfig(
        server=os.environ["NARADA_PROXY_SERVER"],
        credentials_secret_arn=os.getenv("NARADA_PROXY_CREDENTIALS_SECRET_ARN"),
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

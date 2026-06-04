import asyncio

from narada import Agent, BrowserConfig, BrowserEnvironment, ProxyConfig


async def main() -> None:
    proxy = ProxyConfig(
        server="http://proxy.example.com:8080",
        username="your_username",  # optional
        password="your_password",  # optional
        # bypass=".example.com, internal.corp",  # optional, comma-separated domains to bypass
        # ignore_cert_errors=True,  # enable for proxies that do HTTPS inspection (MITM)
    )

    config = BrowserConfig(proxy=proxy)

    env = BrowserEnvironment(config=config)
    agent = Agent(environment=env)

    try:
        # Browser traffic now routes through the proxy.
        response = await agent.run(
            prompt="Go to https://httpbin.org/ip and tell me what IP address is shown.",
        )

        print("Response:", response.text)
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())

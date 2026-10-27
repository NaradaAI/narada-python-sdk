<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/NaradaAI/narada-python-sdk/main/static/Narada-logo-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/NaradaAI/narada-python-sdk/main/static/Narada-logo.png">
  <img alt="NARADA AI Logo." src="https://raw.githubusercontent.com/NaradaAI/narada-python-sdk/main/static/Narada-logo.png" width="300">
</picture>
</p>

<h1 align="center">Computer Use for Agentic Process Automation!</h1>

<p align="center">
  <a href="https://narada.ai"><img src="https://img.shields.io/badge/Sign%20Up-Cloud-blue?logo=cloud" alt="Sign Up"></a>
  <a href="https://docs.narada.ai"><img src="https://img.shields.io/badge/Documentation-Docs-blue?logo=gitbook" alt="Documentation"></a>
  <a href="https://x.com/intent/user?screen_name=Narada_AI"><img src="https://img.shields.io/badge/Follow-Twitter-1DA1F2?logo=twitter&logoColor=white" alt="Twitter Follow"></a>
  <a href="https://www.linkedin.com/company/97417492/"><img src="https://img.shields.io/badge/Follow-LinkedIn-0077B5?logo=linkedin&logoColor=white" alt="LinkedIn Follow"></a>
</p>

The official Narada Python SDK that helps you launch browsers and run tasks with Narada UI agents.

## Installation

```bash
pip install narada
```

## Quick Start

**Important**: The first time Narada opens the automated browser, you will need to manually install the [Narada Enterprise extension](https://chromewebstore.google.com/detail/enterprise-narada-ai-assi/bhioaidlggjdkheaajakomifblpjmokn) and log in to your Narada account.

After installation and login, create a Narada API Key (see [this link](https://docs.narada.ai/documentation/authentication#api-key) for instructions) and set the following environment variable:

```bash
export NARADA_API_KEY=<YOUR KEY>
```

That's it. Now you can run the following code to create a browser environment and ask an
agent to download a file for you from arxiv:

```python
import asyncio

from narada import Agent, AgentKind, BrowserEnvironment


async def main() -> None:
    # Create the browser environment. It initializes lazily on the first action.
    env = BrowserEnvironment()
    agent = Agent(environment=env)
    mini_agent = Agent(environment=env, kind=AgentKind.OPERATOR_MINI)

    try:
        # Run a task in this browser environment.
        response = await agent.run(
            prompt='Search for "LLM Compiler" on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.',
            # Optionally generate a GIF of the agent's actions.
            generate_gif=True,
        )

        print("Response:", response.model_dump_json(indent=2))

        # Use the product's lower-cost tier when appropriate.
        mini_response = await mini_agent.run(prompt="Summarize the completed task.")
        print("Mini response:", mini_response.model_dump_json(indent=2))
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())
```

`AgentKind.OPERATOR_MINI` and `AgentKind.CORE_AGENT_MINI` select the lower-cost Mini variants of
their respective product agents. Named Agent Studio workflows continue to use their persisted Agent
steps.

This would then result in the following trajectory:

<p align="center">
  <a href="https://youtu.be/bpy-xnSeboY">
    <img src="https://i.imgur.com/TyEuD5d.gif" alt="File Download Example" width="600">
  </a>
</p>

You can use the SDK to launch browsers and run automated tasks using natural language instructions. For more examples and code samples, please explore the [`examples/`](examples/) folder in this repository.

## Migration note

This version introduces a non-backward-compatible, agent-centered API:

- Create an execution target with an environment, such as `BrowserEnvironment`,
  `CloudBrowserEnvironment`, `RemoteBrowserEnvironment`, or `LambdaEnvironment`.
- Create an `Agent(environment=env, kind=...)` and call `await agent.run(prompt=...)`.
- Browser actions such as `go_to_url`, `agentic_selector`, and sheet operations are now methods on
  `Agent`.
- Environments keep lifecycle/bookkeeping APIs such as `start()`, `close()`,
  `browser_window_id`, and `cloud_browser_session_id`.

## Features

- **Natural Language Control**: Send instructions in plain English to control browser actions
- **Parallel Execution**: Run multiple browser tasks simultaneously across different windows
- **Error Handling**: Built-in timeout handling and retry mechanisms
- **Action Recording**: Generate GIFs of agent actions for debugging and documentation
- **Async Support**: Full async/await support for efficient operations

## Key Capabilities

- **Web Search & Navigation**: Automatically search, click links, and navigate websites
- **Data Extraction**: Extract information from web pages using AI understanding
- **Form Interaction**: Fill out forms and interact with web elements
- **File Operations**: Download files and handle web-based documents
- **Vector Stores**: Discover managed Agent Studio stores or attach an Amazon Bedrock Knowledge Base
- **Multi-window Management**: Coordinate tasks across multiple browser instances

## Vector Stores

Attach a managed Agent Studio vector store to an agent run without copying its provider-side ID:

Managed vector-store paths are canonical and owner-qualified, using the format
`/owner@email.com/path/to/store`.

```python
env = BrowserEnvironment()
store = await env.vector_stores.get(
    path="/owner@example.com/Knowledge/Product documentation"
)
response = await Agent(environment=env, kind=AgentKind.PRODUCTIVITY).run(
    "Answer from the attached knowledge base and cite source filenames.",
    vector_stores=[store],
)
```

See the managed and external examples in
[`examples/04_extending_the_agent/`](examples/04_extending_the_agent/).

## Logging

The SDK logs through standard `logging` loggers named after its modules, such as
`narada.environment`, all under the `narada` logger. It installs no handlers and leaves levels and
propagation alone, so Narada records go wherever your application's logging configuration sends
them. Without any configuration, Python prints warnings and errors to stderr.

To print Narada logs as `[narada.<module>.<function>:<line>] <message>`, call `enable_logging`:

```python
import logging

import narada

narada.enable_logging(logging.DEBUG)
```

If your application configures logging itself, Narada records propagate to its handlers. Pass
`narada.LOG_FORMAT` to your formatter to use the same format there:

```python
logging.basicConfig(level=logging.INFO, format=narada.LOG_FORMAT)
logging.getLogger("narada").setLevel(logging.DEBUG)
```

Use one approach or the other: `enable_logging` adds its own handler, so combining it with root
handlers prints each Narada record twice.

### Time profiling

At `DEBUG` level, the SDK logs how long each high-level step took, such as launching Chrome,
connecting over CDP, waiting for the Narada extension, submitting an agent request, and waiting for
its result:

```text
[narada.environment._launch_browser_once:1515] Time profile: action=start phase=launch_chrome outcome=ok elapsed_ms=412
[narada.environment._initialize_launched_browser:1585] Time profile: action=start phase=connect_cdp attempt=1 outcome=ok elapsed_ms=96
[narada.environment._ensure_initialized:697] Time profile: action=start phase=total environment=BrowserEnvironment outcome=ok elapsed_ms=6184
[narada.environment._dispatch_request:1035] Time profile: action=agent_run phase=wait_for_completion request_id=... outcome=ok elapsed_ms=41230
```

`action` is the SDK operation (`start`, `agent_run`, `extension_action`, or `close`), `phase` is
the step within it, and `outcome` is `ok` or the name of the exception that ended the step. Each
record also carries these values as a `narada_time_profile` dictionary attribute for structured log
handlers.

## License

This project is licensed under the Apache 2.0 License.

## Support

For questions, issues, or support, please contact: support@narada.ai

## Citation

We appreciate it if you could cite Narada if you found it useful for your project.

```bibtex
@software{narada_ai2025,
  author = {Narada AI},
  title = {Narada AI: Agentic Process Automation for Enterprise},
  year = {2025},
  publisher = {GitHub},
  url = {https://github.com/NaradaAI/narada-python-sdk}
}
```

<div align="center">
Made with ❤️ in Berkeley, CA.
</div>

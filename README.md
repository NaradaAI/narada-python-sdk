<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./static/Narada-logo-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="./static/Narada-logo.png">
  <img alt="NARADA AI Logo." src="./static/Narada-logo.png" width="300">
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

That's it. Now you can run the following code to spin up Narada to go and download a file for you from arxiv:

```python
import asyncio

from narada import Narada


async def main() -> None:
    # Initialize the Narada client.
    async with Narada() as narada:
        # Open a new browser window and initialize the Narada UI agent.
        window = await narada.open_and_initialize_browser_window()

        # Run a task in this browser window.
        response = await window.dispatch_request(
            prompt='/Operator Search for "LLM Compiler" on Google and open the first arXiv paper on the results page, then open the PDF. Then download the PDF of the paper.',
            # Optionally generate a GIF of the agent's actions.
            generate_gif=True,
        )
        print("Response:", response["response"]["text"])


if __name__ == "__main__":
    asyncio.run(main())
```

This would then result in the following trajectory:

<p align="center">
  <a href="https://youtu.be/bpy-xnSeboY">
    <img src="https://i.imgur.com/TyEuD5d.gif" alt="File Download Example" width="600">
  </a>
</p>

You can use the SDK to launch browsers and run automated tasks using natural language instructions. For more examples and code samples, please explore the [`examples/`](examples/) folder in this repository.

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
- **Multi-window Management**: Coordinate tasks across multiple browser instances

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

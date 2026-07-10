# Narada SDK Examples

Runnable, single-file examples for the Narada Python SDK, organized as a guided tour. If you're new, start at [`01_getting_started/01_run_your_first_task.py`](01_getting_started/01_run_your_first_task.py) and work through the folders in order — later sections build on ideas from earlier ones.

## Running an example

1. Install dependencies from the repo root: `uv sync`
2. Set your API key: `export NARADA_API_KEY=...` (get one at [app.narada.ai](https://app.narada.ai))
3. Run any example:

```sh
uv run python examples/01_getting_started/01_run_your_first_task.py
```

## 01 — Getting started

| Example | What it shows |
| --- | --- |
| [`01_run_your_first_task.py`](01_getting_started/01_run_your_first_task.py) | Open a browser and run your first natural-language task. Also shows secret variables (kept hidden from the LLM) and GIF generation. |
| [`02_choose_an_agent.py`](01_getting_started/02_choose_an_agent.py) | Pick which built-in agent handles a task (e.g. the Core Agent instead of the default Operator). |
| [`03_multi_turn_conversation.py`](01_getting_started/03_multi_turn_conversation.py) | Continue a conversation across multiple `run()` calls with `previous_request_id`. |
| [`04_get_structured_output.py`](01_getting_started/04_get_structured_output.py) | Get typed results back by passing a Pydantic model as `output_schema`. |

## 02 — Building workflows

| Example | What it shows |
| --- | --- |
| [`01_chain_tasks_into_a_workflow.py`](02_building_workflows/01_chain_tasks_into_a_workflow.py) | Chain agent calls: extract structured data with one agent, then act on each result with another. |
| [`02_run_tasks_in_parallel.py`](02_building_workflows/02_run_tasks_in_parallel.py) | Run independent tasks concurrently, each in its own browser window. |
| [`03_parallel_windows_sharing_data.py`](02_building_workflows/03_parallel_windows_sharing_data.py) | Coordinate two browser windows that pass data between their tasks. |
| [`04_handle_timeouts.py`](02_building_workflows/04_handle_timeouts.py) | Catch `NaradaTimeoutError` and retry without losing browser state. |
| [`05_verify_results_with_a_critic.py`](02_building_workflows/05_verify_results_with_a_critic.py) | Attach a critic that checks whether the agent actually completed the task and extracts structured details from its run. |
| [`06_ask_the_user_for_input.py`](02_building_workflows/06_ask_the_user_for_input.py) | Pause for human input or approval mid-workflow (human-in-the-loop). |

## 03 — Files and data

| Example | What it shows |
| --- | --- |
| [`01_attach_a_file.py`](03_files_and_data/01_attach_a_file.py) | Send a local file to the agent as an attachment. |
| [`02_pass_files_as_input_variables.py`](03_files_and_data/02_pass_files_as_input_variables.py) | Reference files in your prompt via `input_variables`; the SDK uploads them automatically. |
| [`03_read_and_write_google_sheets.py`](03_files_and_data/03_read_and_write_google_sheets.py) | Read from and write to Google Sheets. |
| [`04_read_and_write_excel.py`](03_files_and_data/04_read_and_write_excel.py) | Read from and write to Excel workbooks via a connected Microsoft account. |
| [`05_save_files_to_downloads.py`](03_files_and_data/05_save_files_to_downloads.py) | Save generated text or binary files to the Downloads directory. |
| [`06_render_html_output.py`](03_files_and_data/06_render_html_output.py) | Display an HTML report to the user. |

`demo_attachment_file.txt` and `demo_image.png` are fixtures used by the examples above.

## 04 — Extending the agent

| Example | What it shows |
| --- | --- |
| [`01_run_your_agent_studio_agent.py`](04_extending_the_agent/01_run_your_agent_studio_agent.py) | Invoke a custom agent you built in Agent Studio by its path. |
| [`02_connect_mcp_tools.py`](04_extending_the_agent/02_connect_mcp_tools.py) | Give the agent extra tools from an MCP server for a single run. |

## 05 — Browser setups

| Example | What it shows |
| --- | --- |
| [`01_attach_to_your_own_chrome.py`](05_browser_setups/01_attach_to_your_own_chrome.py) | Attach the SDK to a Chrome instance you launched yourself via CDP. |
| [`02_run_in_a_cloud_browser.py`](05_browser_setups/02_run_in_a_cloud_browser.py) | Run tasks in a Narada-hosted cloud browser session, including session lifecycle and downloaded files. |
| [`03_control_a_browser_on_another_machine.py`](05_browser_setups/03_control_a_browser_on_another_machine.py) | Drive a browser window running on a different machine by its window ID. |
| [`04_route_traffic_through_a_proxy.py`](05_browser_setups/04_route_traffic_through_a_proxy.py) | Route all browser traffic through an HTTP/SOCKS proxy. |
| [`05_split_script_browser_handoff.py`](05_browser_setups/05_split_script_browser_handoff.py) | Start a browser in one process, then reuse and close it from later processes. |

## 06 — Page actions

Low-level, deterministic browser actions with an AI fallback — useful when you need precise control instead of a natural-language prompt.

| Example | What it shows |
| --- | --- |
| [`01_get_the_current_url.py`](06_page_actions/01_get_the_current_url.py) | Read the current page URL. |
| [`02_click_and_fill_with_selectors.py`](06_page_actions/02_click_and_fill_with_selectors.py) | Click and fill elements by CSS/XPath selectors, falling back to the Operator agent if they don't match. |
| [`03_read_element_text_and_properties.py`](06_page_actions/03_read_element_text_and_properties.py) | Read text content and DOM properties from elements. |
| [`04_replay_recorded_mouse_actions.py`](06_page_actions/04_replay_recorded_mouse_actions.py) | Replay recorded clicks, fills, and scrolls at viewport coordinates, with an AI fallback. |
| [`05_send_keyboard_events.py`](06_page_actions/05_send_keyboard_events.py) | Send raw keyboard events, including modifier combinations. |

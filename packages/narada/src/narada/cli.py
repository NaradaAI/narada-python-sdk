from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from narada.browser_workbench import (
    browser_diff,
    browser_downloads,
    browser_find,
    browser_goto,
    browser_nrd_action,
    browser_screenshot,
    browser_selectors,
    browser_snapshot,
    env_close,
    env_open,
    env_status,
)
from narada.studio import (
    AgentStudioWorkbenchClient,
    studio_delete,
    studio_diff,
    studio_export,
    studio_get,
    studio_list,
    studio_project_diff,
    studio_project_export,
    studio_resolve,
    studio_run,
    studio_sync_python_project,
    studio_upsert_python,
)
from narada.workbench import (
    _redact_sensitive_text,
    default_api_base_url,
    default_auth_headers,
    materialize_execution_trace_context,
    materialize_execution_trace_from_request_id,
    score_proof_root,
    verify_proof_root,
)


def _print(value: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    status = value.get("status", "unknown")
    proof_root = value.get("proofRoot") or value.get("path")
    print(f"status: {status}")
    if proof_root:
        print(f"proofRoot: {proof_root}")


def _load_context_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Context file must contain a JSON object")
    context = payload.get("executionTraceContext") or payload.get("context") or payload
    if not isinstance(context, dict):
        raise ValueError(
            "Context file must contain executionTraceContext or context object"
        )
    return context


def _studio_client(args: argparse.Namespace) -> AgentStudioWorkbenchClient:
    return AgentStudioWorkbenchClient(
        auth_headers=default_auth_headers(),
        base_url=args.base_url or default_api_base_url(),
    )


async def _trace_materialize(args: argparse.Namespace) -> int:
    auth_headers = default_auth_headers()
    base_url = args.base_url or default_api_base_url()
    if args.context_file:
        source_run = None
        if args.source_status or args.source_request_id:
            source_run = {
                "type": args.source_type,
                "authority": "caller-attested",
                "status": args.source_status or "unknown",
                "requestId": args.source_request_id,
            }
        result = await materialize_execution_trace_context(
            _load_context_file(Path(args.context_file)),
            out=args.out,
            source_run=source_run,
            auth_headers=auth_headers,
            base_url=base_url,
        )
    else:
        result = await materialize_execution_trace_from_request_id(
            args.request_id,
            out=args.out,
            auth_headers=auth_headers,
            base_url=base_url,
        )
    payload = {
        "schemaVersion": 1,
        "status": result.report["status"],
        "path": str(result.path),
        "proofRoot": str(result.path),
        "artifactCount": result.report["artifactCount"],
        "warnings": result.report["warnings"],
    }
    _print(payload, as_json=args.json)
    return 0 if result.report["status"] in {"passed", "needs_review"} else 1


def _score(args: argparse.Namespace) -> int:
    result = score_proof_root(args.proof_root)
    _print(result, as_json=args.json)
    return 0 if result["status"] == "passed" else 1


def _verify(args: argparse.Namespace) -> int:
    result = verify_proof_root(args.proof_root)
    _print(result, as_json=args.json)
    return 0 if result["verified"] else 1


async def _studio_list(args: argparse.Namespace) -> int:
    result = await studio_list(
        parent_path=args.parent_path,
        proof_root=args.proof_root,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_resolve(args: argparse.Namespace) -> int:
    result = await studio_resolve(
        path=args.path,
        proof_root=args.proof_root,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_get(args: argparse.Namespace) -> int:
    result = await studio_get(
        item_id=args.item_id,
        proof_root=args.proof_root,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_export(args: argparse.Namespace) -> int:
    result = await studio_export(
        item_id=args.item_id,
        out=args.out,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_diff(args: argparse.Namespace) -> int:
    result = await studio_diff(
        item_id=args.item_id,
        file=args.file,
        proof_root=args.proof_root,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_upsert_python(args: argparse.Namespace) -> int:
    if args.apply and not args.proof_root:
        raise ValueError("--proof-root is required with --apply")
    result = await studio_upsert_python(
        name=args.name,
        parent_path=args.parent_path,
        file=args.file,
        apply=args.apply,
        proof_root=args.proof_root,
        update_item_id=args.update_item_id,
        expected_remote_code_hash=args.expected_remote_code_hash,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_run(args: argparse.Namespace) -> int:
    if not args.trace:
        raise ValueError("studio run requires --trace for M3 proof")
    result = await studio_run(
        item_id=args.item_id,
        proof_root=args.proof_root,
        prompt_suffix=args.prompt_suffix,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_delete(args: argparse.Namespace) -> int:
    if not args.proof_root:
        raise ValueError("studio delete requires --proof-root for command provenance")
    result = await studio_delete(
        item_id=args.item_id,
        expected_name=args.expected_name,
        created_by_command_id=args.created_by_command_id,
        proof_root=args.proof_root,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_sync_python_project(args: argparse.Namespace) -> int:
    if args.apply and not args.proof_root:
        raise ValueError("--proof-root is required with --apply")
    if not args.apply and not args.proof_root:
        raise ValueError("--proof-root is required for sync-python-project")
    command = [
        "narada",
        "workbench",
        "studio",
        "sync-python-project",
        "--local",
        args.local,
        "--name",
        args.name,
        "--parent-path",
        args.parent_path,
        "--entrypoint",
        args.entrypoint,
        "--apply" if args.apply else "--dry-run",
    ]
    result = await studio_sync_python_project(
        local=args.local,
        name=args.name,
        parent_path=args.parent_path,
        entrypoint=args.entrypoint,
        apply=args.apply,
        proof_root=args.proof_root,
        update_item_id=args.update_item_id,
        expected_remote_code_hash=args.expected_remote_code_hash,
        client=_studio_client(args),
        regeneration_command=" ".join(command),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_project_diff(args: argparse.Namespace) -> int:
    result = await studio_project_diff(
        local=args.local,
        item_id=args.item_id,
        proof_root=args.proof_root,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _studio_project_export(args: argparse.Namespace) -> int:
    result = await studio_project_export(
        item_id=args.item_id,
        out=args.out,
        proof_root=args.proof_root,
        client=_studio_client(args),
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _env_open(args: argparse.Namespace) -> int:
    result = await env_open(
        name=args.name,
        kind=args.kind,
        proof_root=args.proof_root,
        base_url=args.base_url,
        initialization_url=args.initialization_url,
        cdp_port=args.cdp_port,
        extension_id=args.extension_id,
        user_data_dir=args.user_data_dir,
        profile_directory=args.profile_directory,
        attach_to_existing=args.attach_to_existing,
        browser_window_id=args.browser_window_id,
        cloud_browser_session_id=args.cloud_browser_session_id,
        session_name=args.session_name,
        session_timeout=args.session_timeout,
        dev_app_origin_override=args.dev_app_origin_override,
        dev_extension_s3_bucket=args.dev_extension_s3_bucket,
        dev_extension_s3_key=args.dev_extension_s3_key,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _env_status(args: argparse.Namespace) -> int:
    result = await env_status(
        env_id=args.env,
        proof_root=args.proof_root,
        base_url=args.base_url,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _env_close(args: argparse.Namespace) -> int:
    result = await env_close(
        env_id=args.env,
        proof_root=args.proof_root,
        base_url=args.base_url,
        close_adopted=args.close_adopted,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _browser_goto(args: argparse.Namespace) -> int:
    result = await browser_goto(
        env_id=args.env,
        url=args.url,
        proof_root=args.proof_root,
        base_url=args.base_url,
        new_tab=args.new_tab,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _browser_snapshot(args: argparse.Namespace) -> int:
    result = await browser_snapshot(
        env_id=args.env,
        proof_root=args.proof_root,
        base_url=args.base_url,
        max_html_bytes=args.max_html_bytes,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _browser_find(args: argparse.Namespace) -> int:
    result = await browser_find(
        env_id=args.env,
        snapshot_id=args.snapshot_id,
        proof_root=args.proof_root,
        text=args.text,
        tag_name=args.tag_name,
        data_nrd=args.data_nrd,
        interactive_only=args.interactive_only,
        limit=args.limit,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _browser_selectors(args: argparse.Namespace) -> int:
    result = await browser_selectors(
        env_id=args.env,
        snapshot_id=args.snapshot_id,
        frame_id=args.frame_id,
        data_nrd=args.data_nrd,
        proof_root=args.proof_root,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _browser_nrd_action(args: argparse.Namespace, action: str) -> int:
    result = await browser_nrd_action(
        env_id=args.env,
        action=action,
        snapshot_id=args.snapshot_id,
        frame_id=args.frame_id,
        data_nrd=args.data_nrd,
        proof_root=args.proof_root,
        base_url=args.base_url,
        value=getattr(args, "value", None),
        post_snapshot=args.post_snapshot,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _browser_diff(args: argparse.Namespace) -> int:
    result = await browser_diff(
        env_id=args.env,
        before=args.before,
        after=args.after,
        proof_root=args.proof_root,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _browser_screenshot(args: argparse.Namespace) -> int:
    result = await browser_screenshot(
        env_id=args.env,
        proof_root=args.proof_root,
        base_url=args.base_url,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


async def _browser_downloads(args: argparse.Namespace) -> int:
    result = await browser_downloads(
        env_id=args.env,
        proof_root=args.proof_root,
        base_url=args.base_url,
    )
    _print({**result.payload, "commandId": result.command_id}, as_json=args.json)
    return 0 if result.status == "passed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="narada")
    subparsers = parser.add_subparsers(dest="command")
    workbench = subparsers.add_parser("workbench")
    workbench_subparsers = workbench.add_subparsers(dest="workbench_command")

    trace_parser = workbench_subparsers.add_parser("trace")
    trace_subparsers = trace_parser.add_subparsers(dest="trace_command")
    materialize = trace_subparsers.add_parser("materialize")
    materialize_source = materialize.add_mutually_exclusive_group(required=True)
    materialize_source.add_argument("--context-file")
    materialize_source.add_argument("--request-id")
    materialize.add_argument("--out")
    materialize.add_argument("--base-url")
    materialize.add_argument("--source-status")
    materialize.add_argument("--source-request-id")
    materialize.add_argument("--source-type", default="external")
    materialize.add_argument("--json", action="store_true")
    materialize.set_defaults(handler=lambda args: asyncio.run(_trace_materialize(args)))

    score = workbench_subparsers.add_parser("score")
    score.add_argument("proof_root")
    score.add_argument("--json", action="store_true")
    score.set_defaults(handler=_score)

    verify = workbench_subparsers.add_parser("verify")
    verify.add_argument("proof_root")
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(handler=_verify)

    env_parser = workbench_subparsers.add_parser("env")
    env_subparsers = env_parser.add_subparsers(dest="env_command")

    env_open_parser = env_subparsers.add_parser("open")
    env_open_parser.add_argument("--kind", default="local")
    env_open_parser.add_argument("--name", required=True)
    env_open_parser.add_argument("--proof-root", required=True)
    env_open_parser.add_argument("--base-url")
    env_open_parser.add_argument("--initialization-url")
    env_open_parser.add_argument("--cdp-port", type=int)
    env_open_parser.add_argument("--extension-id")
    env_open_parser.add_argument("--user-data-dir")
    env_open_parser.add_argument("--profile-directory")
    env_open_parser.add_argument("--attach-to-existing", action="store_true")
    env_open_parser.add_argument("--browser-window-id")
    env_open_parser.add_argument("--cloud-browser-session-id")
    env_open_parser.add_argument("--session-name")
    env_open_parser.add_argument("--session-timeout", type=int)
    env_open_parser.add_argument("--dev-app-origin-override")
    env_open_parser.add_argument("--dev-extension-s3-bucket")
    env_open_parser.add_argument("--dev-extension-s3-key")
    env_open_parser.add_argument("--json", action="store_true")
    env_open_parser.set_defaults(handler=lambda args: asyncio.run(_env_open(args)))

    env_status_parser = env_subparsers.add_parser("status")
    env_status_parser.add_argument("env")
    env_status_parser.add_argument("--proof-root", required=True)
    env_status_parser.add_argument("--base-url")
    env_status_parser.add_argument("--json", action="store_true")
    env_status_parser.set_defaults(handler=lambda args: asyncio.run(_env_status(args)))

    env_close_parser = env_subparsers.add_parser("close")
    env_close_parser.add_argument("env")
    env_close_parser.add_argument("--proof-root", required=True)
    env_close_parser.add_argument("--base-url")
    env_close_parser.add_argument(
        "--close-adopted",
        action="store_true",
        help="Also close an adopted browser window. By default adopted windows are detached, not closed.",
    )
    env_close_parser.add_argument("--json", action="store_true")
    env_close_parser.set_defaults(handler=lambda args: asyncio.run(_env_close(args)))

    browser_parser = workbench_subparsers.add_parser("browser")
    browser_subparsers = browser_parser.add_subparsers(dest="browser_command")

    browser_goto_parser = browser_subparsers.add_parser("goto")
    browser_goto_parser.add_argument("env")
    browser_goto_parser.add_argument("--url", required=True)
    browser_goto_parser.add_argument("--proof-root", required=True)
    browser_goto_parser.add_argument("--base-url")
    browser_goto_parser.add_argument("--new-tab", action="store_true")
    browser_goto_parser.add_argument("--json", action="store_true")
    browser_goto_parser.set_defaults(
        handler=lambda args: asyncio.run(_browser_goto(args))
    )

    browser_snapshot_parser = browser_subparsers.add_parser("snapshot")
    browser_snapshot_parser.add_argument("env")
    browser_snapshot_parser.add_argument("--proof-root", required=True)
    browser_snapshot_parser.add_argument("--base-url")
    browser_snapshot_parser.add_argument("--max-html-bytes", type=int, default=500_000)
    browser_snapshot_parser.add_argument("--json", action="store_true")
    browser_snapshot_parser.set_defaults(
        handler=lambda args: asyncio.run(_browser_snapshot(args))
    )

    browser_find_parser = browser_subparsers.add_parser("find")
    browser_find_parser.add_argument("env")
    browser_find_parser.add_argument("--snapshot-id", required=True)
    browser_find_parser.add_argument("--proof-root", required=True)
    browser_find_parser.add_argument("--text")
    browser_find_parser.add_argument("--tag-name")
    browser_find_parser.add_argument("--data-nrd")
    browser_find_parser.add_argument("--interactive-only", action="store_true")
    browser_find_parser.add_argument("--limit", type=int, default=20)
    browser_find_parser.add_argument("--json", action="store_true")
    browser_find_parser.set_defaults(
        handler=lambda args: asyncio.run(_browser_find(args))
    )

    browser_selectors_parser = browser_subparsers.add_parser("selectors")
    browser_selectors_parser.add_argument("env")
    browser_selectors_parser.add_argument("--snapshot-id", required=True)
    browser_selectors_parser.add_argument("--frame-id", required=True)
    browser_selectors_parser.add_argument("--data-nrd", required=True)
    browser_selectors_parser.add_argument("--proof-root", required=True)
    browser_selectors_parser.add_argument("--json", action="store_true")
    browser_selectors_parser.set_defaults(
        handler=lambda args: asyncio.run(_browser_selectors(args))
    )

    for command_name, action_name in (
        ("click-nrd", "click"),
        ("fill-nrd", "fill"),
        ("select-nrd", "select"),
    ):
        nrd_parser = browser_subparsers.add_parser(command_name)
        nrd_parser.add_argument("env")
        nrd_parser.add_argument("--snapshot-id", required=True)
        nrd_parser.add_argument("--frame-id", required=True)
        nrd_parser.add_argument("--data-nrd", required=True)
        nrd_parser.add_argument("--proof-root", required=True)
        nrd_parser.add_argument("--base-url")
        if action_name in {"fill", "select"}:
            nrd_parser.add_argument("--value", required=True)
        nrd_parser.add_argument(
            "--post-snapshot",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=(
                "Capture a post-action snapshot for proof. Use --no-post-snapshot "
                "only for diagnostic commands that should verify as needs_review."
            ),
        )
        nrd_parser.add_argument("--json", action="store_true")
        nrd_parser.set_defaults(
            handler=lambda args, selected_action=action_name: asyncio.run(
                _browser_nrd_action(args, selected_action)
            )
        )

    browser_diff_parser = browser_subparsers.add_parser("diff")
    browser_diff_parser.add_argument("env")
    browser_diff_parser.add_argument("--before", required=True)
    browser_diff_parser.add_argument("--after", required=True)
    browser_diff_parser.add_argument("--proof-root", required=True)
    browser_diff_parser.add_argument("--json", action="store_true")
    browser_diff_parser.set_defaults(
        handler=lambda args: asyncio.run(_browser_diff(args))
    )

    browser_screenshot_parser = browser_subparsers.add_parser("screenshot")
    browser_screenshot_parser.add_argument("env")
    browser_screenshot_parser.add_argument("--proof-root", required=True)
    browser_screenshot_parser.add_argument("--base-url")
    browser_screenshot_parser.add_argument("--json", action="store_true")
    browser_screenshot_parser.set_defaults(
        handler=lambda args: asyncio.run(_browser_screenshot(args))
    )

    browser_downloads_parser = browser_subparsers.add_parser("downloads")
    browser_downloads_parser.add_argument("env")
    browser_downloads_parser.add_argument("--proof-root", required=True)
    browser_downloads_parser.add_argument("--base-url")
    browser_downloads_parser.add_argument("--json", action="store_true")
    browser_downloads_parser.set_defaults(
        handler=lambda args: asyncio.run(_browser_downloads(args))
    )

    studio_parser = workbench_subparsers.add_parser("studio")
    studio_subparsers = studio_parser.add_subparsers(dest="studio_command")

    studio_list_parser = studio_subparsers.add_parser("list")
    studio_list_parser.add_argument("--parent-path", default="/")
    studio_list_parser.add_argument("--proof-root")
    studio_list_parser.add_argument("--base-url")
    studio_list_parser.add_argument("--json", action="store_true")
    studio_list_parser.set_defaults(
        handler=lambda args: asyncio.run(_studio_list(args))
    )

    studio_resolve_parser = studio_subparsers.add_parser("resolve")
    studio_resolve_parser.add_argument("--path", required=True)
    studio_resolve_parser.add_argument("--proof-root")
    studio_resolve_parser.add_argument("--base-url")
    studio_resolve_parser.add_argument("--json", action="store_true")
    studio_resolve_parser.set_defaults(
        handler=lambda args: asyncio.run(_studio_resolve(args))
    )

    studio_get_parser = studio_subparsers.add_parser("get")
    studio_get_parser.add_argument("--item-id", required=True)
    studio_get_parser.add_argument("--proof-root")
    studio_get_parser.add_argument("--base-url")
    studio_get_parser.add_argument("--json", action="store_true")
    studio_get_parser.set_defaults(handler=lambda args: asyncio.run(_studio_get(args)))

    studio_export_parser = studio_subparsers.add_parser("export")
    studio_export_parser.add_argument("--item-id", required=True)
    studio_export_parser.add_argument("--out", required=True)
    studio_export_parser.add_argument("--base-url")
    studio_export_parser.add_argument("--json", action="store_true")
    studio_export_parser.set_defaults(
        handler=lambda args: asyncio.run(_studio_export(args))
    )

    studio_diff_parser = studio_subparsers.add_parser("diff")
    studio_diff_parser.add_argument("--item-id", required=True)
    studio_diff_parser.add_argument("--file", required=True)
    studio_diff_parser.add_argument("--proof-root")
    studio_diff_parser.add_argument("--base-url")
    studio_diff_parser.add_argument("--json", action="store_true")
    studio_diff_parser.set_defaults(
        handler=lambda args: asyncio.run(_studio_diff(args))
    )

    studio_upsert_parser = studio_subparsers.add_parser("upsert-python")
    studio_upsert_parser.add_argument("--name", required=True)
    studio_upsert_parser.add_argument("--parent-path", default="/")
    studio_upsert_parser.add_argument("--file", required=True)
    studio_apply_group = studio_upsert_parser.add_mutually_exclusive_group()
    studio_apply_group.add_argument("--dry-run", action="store_true", dest="dry_run")
    studio_apply_group.add_argument("--apply", action="store_true")
    studio_upsert_parser.add_argument("--proof-root")
    studio_upsert_parser.add_argument("--update-item-id")
    studio_upsert_parser.add_argument("--expected-remote-code-hash")
    studio_upsert_parser.add_argument("--base-url")
    studio_upsert_parser.add_argument("--json", action="store_true")
    studio_upsert_parser.set_defaults(
        dry_run=True,
        handler=lambda args: asyncio.run(_studio_upsert_python(args)),
    )

    studio_run_parser = studio_subparsers.add_parser("run")
    studio_run_parser.add_argument("--item-id", required=True)
    studio_run_parser.add_argument("--trace", action="store_true")
    studio_run_parser.add_argument("--proof-root")
    studio_run_parser.add_argument("--prompt-suffix")
    studio_run_parser.add_argument("--base-url")
    studio_run_parser.add_argument("--json", action="store_true")
    studio_run_parser.set_defaults(handler=lambda args: asyncio.run(_studio_run(args)))

    studio_delete_parser = studio_subparsers.add_parser("delete")
    studio_delete_parser.add_argument("--item-id", required=True)
    studio_delete_parser.add_argument("--expected-name", required=True)
    studio_delete_parser.add_argument("--created-by-command-id", required=True)
    studio_delete_parser.add_argument("--proof-root")
    studio_delete_parser.add_argument("--base-url")
    studio_delete_parser.add_argument("--json", action="store_true")
    studio_delete_parser.set_defaults(
        handler=lambda args: asyncio.run(_studio_delete(args))
    )

    studio_sync_parser = studio_subparsers.add_parser("sync-python-project")
    studio_sync_parser.add_argument("--local", required=True)
    studio_sync_parser.add_argument("--name", required=True)
    studio_sync_parser.add_argument("--parent-path", default="/")
    studio_sync_parser.add_argument("--entrypoint", required=True)
    studio_sync_apply_group = studio_sync_parser.add_mutually_exclusive_group()
    studio_sync_apply_group.add_argument(
        "--dry-run", action="store_true", dest="dry_run"
    )
    studio_sync_apply_group.add_argument("--apply", action="store_true")
    studio_sync_parser.add_argument("--proof-root", required=True)
    studio_sync_parser.add_argument("--update-item-id")
    studio_sync_parser.add_argument("--expected-remote-code-hash")
    studio_sync_parser.add_argument("--base-url")
    studio_sync_parser.add_argument("--json", action="store_true")
    studio_sync_parser.set_defaults(
        dry_run=True,
        handler=lambda args: asyncio.run(_studio_sync_python_project(args)),
    )

    studio_project_diff_parser = studio_subparsers.add_parser("project-diff")
    studio_project_diff_parser.add_argument("--local", required=True)
    studio_project_diff_parser.add_argument("--item-id", required=True)
    studio_project_diff_parser.add_argument("--proof-root")
    studio_project_diff_parser.add_argument("--base-url")
    studio_project_diff_parser.add_argument("--json", action="store_true")
    studio_project_diff_parser.set_defaults(
        handler=lambda args: asyncio.run(_studio_project_diff(args))
    )

    studio_project_export_parser = studio_subparsers.add_parser("project-export")
    studio_project_export_parser.add_argument("--item-id", required=True)
    studio_project_export_parser.add_argument("--out", required=True)
    studio_project_export_parser.add_argument("--proof-root")
    studio_project_export_parser.add_argument("--base-url")
    studio_project_export_parser.add_argument("--json", action="store_true")
    studio_project_export_parser.set_defaults(
        handler=lambda args: asyncio.run(_studio_project_export(args))
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return int(handler(args))
    except Exception as exc:
        message = _redact_sensitive_text(str(exc))
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "status": "failed",
                        "error": message,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

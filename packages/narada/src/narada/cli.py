from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from narada.studio import (
    AgentStudioWorkbenchClient,
    studio_delete,
    studio_diff,
    studio_export,
    studio_get,
    studio_list,
    studio_resolve,
    studio_run,
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
        print(f"error: {_redact_sensitive_text(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

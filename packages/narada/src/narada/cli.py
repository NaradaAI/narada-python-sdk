from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

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

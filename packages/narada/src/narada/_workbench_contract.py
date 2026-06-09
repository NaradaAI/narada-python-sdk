from __future__ import annotations

from typing import Final

REQUIRED_PROOF_FILES: Final[tuple[str, ...]] = (
    "manifest.json",
    "commands.jsonl",
    "trace/context.json",
    "trace/resolved.json",
    "trace/events.jsonl",
    "trace/scopes.jsonl",
    "trace/timeline.json",
    "trace/artifacts/index.jsonl",
    "reports/materialization-report.json",
    "reports/redaction-report.json",
    "cleanup/status.json",
)

REDACTION_REPORT_JSON: Final[str] = "reports/redaction-report.json"
REDACTION_REPORT_MD: Final[str] = "reports/redaction-report.md"

BINARY_SCAN_SUFFIXES: Final[tuple[str, ...]] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
)

CLEAN_COMMAND_STATUSES: Final[tuple[str, ...]] = (
    "passed",
    "materialized",
    "needs_review",
    "not_applicable",
)

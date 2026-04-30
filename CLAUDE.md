# Project context

`narada-python-sdk` is Narada's public Python SDK — a uv workspace with three packages (`narada`, `narada-core`, `narada-pyodide`) that lets external callers drive Narada agents programmatically. It's one of three sibling repos in the Narada system; shared cross-repo architecture lives in [`architecture-docs/`](./architecture-docs/) (a git submodule).

## Bootstrap shared docs

If `architecture-docs/CLAUDE.md` is missing, initialize the shared docs before following the links below:

```bash
git submodule update --init architecture-docs
```

## Before changing code, read

- [`architecture-docs/CLAUDE.md`](./architecture-docs/CLAUDE.md) — rules for AI coding agents (read **first**)
- [`architecture-docs/overview.md`](./architecture-docs/overview.md) — 10-minute orientation across the three-repo system
- [`architecture-docs/python-sdk.md`](./architecture-docs/python-sdk.md) — workspace layout, parity rule, public types (this repo)
- [`architecture-docs/api-contracts.md`](./architecture-docs/api-contracts.md) — `/remote-dispatch`, `/extension-actions`, and other endpoints this SDK calls
- [`architecture-docs/conventions.md`](./architecture-docs/conventions.md) — naming, code style
- Other docs in `architecture-docs/` for backend / browser-automation / agent-studio context

## When to update the docs

When you change a public type, add a new SDK action, change the wire shape between SDK and backend, or change the parity rule between `narada` and `narada-pyodide` — update `architecture-docs/python-sdk.md` (and `api-contracts.md` if a wire shape moved) **in the same PR**. The full trigger list is in `architecture-docs/CLAUDE.md` §3.

## Updating the submodule pointer

Merge shared documentation changes into `architecture-docs/main` first, then bump this repo's submodule pointer. CI enforces exact equality with `architecture-docs/main`.

```bash
git submodule update --remote architecture-docs
git add architecture-docs
git commit -m "Bump architecture-docs"
```

CI runs a freshness check (`.github/workflows/architecture-docs-freshness.yml`) that fails when the submodule pointer falls behind `architecture-docs/main`.

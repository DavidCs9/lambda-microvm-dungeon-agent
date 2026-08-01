# Contributing

One-dev personal lab. PRs are for mobile review and the merge → Actions release path — not a
formal review process.

## Workflow

1. Branch from `main` (`codex/…` or similar).
2. Keep credentials, auth tokens, account IDs, and session data out of commits.
3. Formatting is automatic: Cursor runs `ruff format` on `.py` edits via `.cursor/hooks/`, and you
   can enable a git pre-commit with `git config core.hooksPath .githooks`. CI still runs
   `ruff format --check`. Before opening a PR, also run `uv run ruff check .`, `uv run mypy`, and
   `uv run pytest` when the change touches Python.
4. Open a PR; merge triggers the sandbox release workflow when deployable paths change. Do not
   `sam deploy` / publish images from a laptop.

## Security-ish caution

This is a lab, but still: be careful with command execution, IAM, auth, and egress. Prefer tests
over hope. Never commit secrets.

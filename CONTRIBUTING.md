# Contributing

Thanks for helping improve the lab.

## Development workflow

1. Open an issue for substantial behavior or architecture changes.
2. Create a focused branch from `main`.
3. Keep credentials, auth tokens, account IDs, and session data out of commits.
4. Formatting is automatic: Cursor runs `ruff format` on `.py` edits via
   `.cursor/hooks/`, and you can enable a git pre-commit with
   `git config core.hooksPath .githooks`. CI still runs `ruff format --check`
   as a safety net. Before opening a PR, also run `uv run ruff check .`,
   `uv run mypy`, and `uv run pytest`.
5. Include tests and documentation for behavior changes.

Commits should be small, descriptive, and independently reviewable. Pull requests should explain the motivation, security impact, test evidence, and cleanup implications for AWS resources.

## Security-sensitive changes

Changes to command execution, IAM, authentication, network egress, lifecycle hooks, or tenant isolation require explicit tests and a short threat analysis in the pull request.

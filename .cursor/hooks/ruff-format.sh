#!/usr/bin/env bash
# Auto-format Python after agent/editor edits so CI ruff format --check stays green.
set -euo pipefail

input="$(cat)"
file_path="$(
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("file_path") or "")' <<<"$input"
)"

[[ -n "$file_path" && "$file_path" == *.py && -f "$file_path" ]] || exit 0

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"

if command -v uv >/dev/null 2>&1; then
  uv run ruff format "$file_path" >/dev/null
elif command -v ruff >/dev/null 2>&1; then
  ruff format "$file_path" >/dev/null
fi

exit 0

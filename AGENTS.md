# 🔬 LAB MANIFESTO — READ FIRST

**This is a personal laboratory, not an enterprise product.**

- **One dev:** David. No code reviews, no approvals, no RFCs, no release process.
- **Speed > ceremony:** Simple implementation directly. No slices, no phases, no plans.
- **No new overhead:** The existing docs (RFCs, etc.) stay as reference. Do NOT add more ceremony on top.
- **PRs yes, for mobile review:** Branch → commit → push → `gh pr create`. David merges from his phone.
- **Infra mínimo viable:** Si algo no se necesita hoy, no se implementa. Sin alarmas extra, sin roles separados, sin patrones enterprise que el lab no requiere.

**When in doubt: ask "is this enterprise over-engineering for a lab?" If yes, don't do it.**

**Deploy lanes:** After a change, pick the minimum validation path — `web/**` → FE only (`npm run dev`); `control_plane/**` / `data_plane/**` / `plane_shared/**` or `infra/control-plane/**` → SAM sandbox deploy; MicroVM game/runtime (`Dockerfile`, guest `api/` and other non-plane `src/dungeon_agent/**`) → publish image / new `IMAGE_VERSION`. Compose only when contracts cross lanes. CI in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) path-filters the same way (FE PRs skip Python/ARM64/package); require the aggregating **CI** check, not individual lane jobs. Details: [`.cursor/rules/deploy-lanes.mdc`](.cursor/rules/deploy-lanes.mdc).

**Mandatory release and cost rules:**

- **Never deploy manually from a laptop or terminal.** For any deployable change, create the `codex/` branch, commit, push, and open a PR with `gh pr create`. David merges the PR; the merge-triggered GitHub Actions workflow is the only deployment path. Do not run `sam package`, `sam deploy`, `aws cloudformation deploy`, image publishing, or equivalent manual release commands locally.
- **Never invoke campaign generation or Bedrock just to test without explicit notice first.** State the expected number of model calls and cost risk, then wait for David's approval before any paid or externally mutating test. Local unit tests and static validation are safe by default.
- When investigating runtime behavior, verify `main` and the deployed prompt-management/runtime configuration first. Do not assume an old local bundle or prompt version is live.

---

# AWS Guidance

- Prefer the AWS MCP Server for AWS interactions — it provides sandboxed
  execution, observability, and audit logging. If unavailable, use the
  AWS CLI directly.
- Before starting a task, check whether a relevant AWS skill is available.
  Load the skill with `retrieve_skill` and prefer its guidance over
  general knowledge.
- When uncertain about specific AWS details (API parameters, permissions,
  limits, error codes), verify against documentation rather than guessing.
  State uncertainty explicitly if you cannot confirm.
- When creating infrastructure, prefer infrastructure-as-code (AWS CDK or
  CloudFormation) over direct CLI commands.
- When working with infrastructure, follow AWS Well-Architected Framework
  principles.
- Do not use em dashes in AWS resource names or descriptions. Use
  hyphens instead.

## Secret Safety

- MUST load the `aws-secrets-manager` skill first for any secret,
  credential, API key, token, or password task. MUST NOT call
  `secretsmanager get-secret-value` or `batch-get-secret-value`, and MUST
  NOT hit the Secrets Manager Agent daemon directly. MUST use
  `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` with
  `asm-exec` so the secret resolves at runtime without entering context.

## Cursor Cloud specific instructions

Dependencies are refreshed automatically on VM start (update script: install `uv`
if missing, `uv sync --all-groups`, `npm --prefix web install`). `uv` lives in
`~/.local/bin` and is on PATH via `~/.bashrc`; new interactive shells find it.

Backend (Python 3.14, managed by `uv`) and frontend (`web/`, React/Vite) commands
are documented in [README.md](README.md) (`## Development`, `## Play (web)`) and
`web/package.json`. Standard dev flow: `uv run ruff check .`, `uv run mypy`,
`uv run pytest`, and `cd web && npm run dev|build`.

Non-obvious caveats for this environment:
- The Vite dev server binds to `localhost`/IPv6 only. Probe it at
  `http://localhost:5173/` (or `http://[::1]:5173/`); `http://127.0.0.1:5173/`
  returns nothing.
- The web SPA needs a deployed AWS sandbox stack (`VITE_HTTP_URL`/`VITE_WS_URL`
  in `web/.env.local`). Without AWS creds it renders the landing page but stays
  "desconectado" — the campaign/play loop over the network cannot be exercised
  here. This is expected, not a setup failure.
- To exercise core game logic without AWS, run the guest FastAPI directly:
  `DUNGEON_WORKSPACE_DIR="$(mktemp -d)" uv run uvicorn dungeon_agent.api.main:app --reload`.
  Endpoints: `PUT /v1/adventure` then `POST /v1/turns` run the authoritative d20
  roll and world mutation. `AdventurePlan` requires at least 3 locations.
- `pytest` enforces `--cov-fail-under=90` (scoped to `dungeon_agent.api`).

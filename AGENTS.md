# 🔬 LAB MANIFESTO — READ FIRST

**This is a personal laboratory, not an enterprise product.**

- **One dev:** David. No code reviews, no approvals, no RFCs, no release process.
- **Speed > ceremony:** Simple implementation directly. No slices, no phases, no plans.
- **No new overhead:** The existing docs (RFCs, etc.) stay as reference. Do NOT add more ceremony on top.
- **PRs yes, for mobile review:** Branch → commit → push → `gh pr create`. David merges from his phone.
- **Infra mínimo viable:** Si algo no se necesita hoy, no se implementa. Sin alarmas extra, sin roles separados, sin patrones enterprise que el lab no requiere.

**When in doubt: ask "is this enterprise over-engineering for a lab?" If yes, don't do it.**

**Deploy lanes:** After a change, pick the minimum validation path — `web/**` → FE only (`npm run dev`); `control_plane/**` / `data_plane/**` / `plane_shared/**` or `infra/control-plane/**` → SAM sandbox deploy; MicroVM game/runtime (`Dockerfile`, guest `api/` and other non-plane `src/dungeon_agent/**`) → publish image / new `IMAGE_VERSION`. Compose only when contracts cross lanes. CI in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) path-filters the same way (FE PRs skip Python/ARM64/package); require the aggregating **CI** check, not individual lane jobs. Details: [`.cursor/rules/deploy-lanes.mdc`](.cursor/rules/deploy-lanes.mdc).

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

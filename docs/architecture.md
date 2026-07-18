# Architecture

The lab separates orchestration from untrusted execution:

1. A local Adventure Architect generates one small, structured one-shot per session.
2. The validated plan is stored inside the session's authenticated MicroVM.
3. A local Dungeon Master turns each free-form action into typed success and failure branches.
4. The MicroVM rolls the d20, validates proposed changes, and applies exactly one branch.
5. Each player session receives a dedicated Lambda MicroVM and workspace.
6. Lifecycle hooks preserve and validate state across suspend and resume.

The FastAPI backend intentionally implements state operations only. Its OpenAPI contract can support a separate web client later. Arbitrary code execution will be added only with MicroVM isolation, resource limits, no AWS credentials, and restricted network egress.

The master orchestrator runs outside the MicroVM. It owns the Bedrock conversation, MicroVM lifecycle, short-lived endpoint token, and player loop. The MicroVM remains a narrow state and tool-execution boundary rather than receiving model credentials.

Application code uses an installable `src` layout and is split by responsibility:

- `src/dungeon_agent/api/` — FastAPI backend hosted inside the MicroVM
- `src/dungeon_agent/cli.py` — CLI parsing and dependency composition
- `src/dungeon_agent/orchestrator/locales.py` — official languages and selection
- `src/dungeon_agent/orchestrator/session.py` — MicroVM lifecycle and API adapter
- `src/dungeon_agent/orchestrator/agents.py` — typed Bedrock architect and Dungeon Master adapters
- `src/dungeon_agent/orchestrator/game.py` — presentation-neutral generated-adventure loop
- `src/dungeon_agent/api/adventure.py` — authoritative d20 and state-change validator
- `src/dungeon_agent/microvm.py` — shared authenticated HTTP and lifecycle primitives
- `src/dungeon_agent/operations/` — image-building and benchmark workflows
- `src/dungeon_agent/resources/locales/` — runtime-loaded language and action-vocabulary JSON
- `evals/` — deterministic state safety and Bedrock adventure-model comparisons

The `scripts/` directory contains only operational entrypoints for building an image and running
the lifecycle benchmark. Reusable behavior remains in the `dungeon_agent` package.

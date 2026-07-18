# Lambda MicroVM Dungeon Agent

A bilingual, AI-directed tabletop adventure that generates a new world and a new playable
protagonist for every session. The terminal client runs locally; each game's authoritative state
and d20 rules live inside a dedicated AWS Lambda MicroVM.

[![CI](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## How this started

This project began as a weekend lab to test the new AWS Lambda MicroVM experience: launch an
isolated VM, reach a small FastAPI service over authenticated HTTPS, preserve state across its
lifecycle, and measure the latency. A tiny dungeon was only supposed to make the infrastructure
test less boring.

Then the dungeon was actually fun to play.

The experiment grew into a bilingual tabletop game with generated worlds, dedicated adventure and
character architects, free-form Dungeon Master adjudication, visible dice, voice, music,
observability, and gameplay evals. The MicroVM lab is still here, but now it protects the rules and
state of a real game I want to keep improving.

## What the game does

At the beginning of a session:

1. The **Adventure Architect** creates a compact fantasy world, conflict, locations, NPCs, items,
   secrets, and objective.
2. The **Character Architect** creates a protagonist grounded in that world: identity, history,
   desire, weakness, contradiction, relationships, prior knowledge, and three optional ways to
   begin.
3. The TUI introduces who you are and why the adventure matters before asking for an action.
4. The **Dungeon Master** interprets free-form actions and proposes success and failure outcomes.
5. The MicroVM rolls the d20, validates the proposal, persists state, and decides victory or defeat.

The player is never limited to a command menu. Suggested openings provide direction, but any
plausible action can be attempted.

## Current experience

- A completely new short adventure and protagonist per session
- Official Spanish and English gameplay
- Free-form actions with visible d20 rolls and original dice audio
- Generated Dungeon Master voice through Amazon Polly
- Original local fantasy ambience
- Live location, inventory, objective, health, and remaining-turn state
- Per-session model calls, tokens, latency, and estimated cost
- Deterministic victory and defeat screens
- An isolated, temporary MicroVM for every game

## Architecture

```text
Local machine
  Textual TUI / plain CLI
          |
  presentation-neutral GamePort
          |
  DungeonOrchestrator
     |       |       |
     |       |       +-- Dungeon Master (Bedrock)
     |       +---------- Character Architect (Bedrock)
     +------------------ Adventure Architect (Bedrock)
          |
  authenticated HTTPS
          |
Dedicated Lambda MicroVM
  FastAPI + authoritative world state + d20 rules
```

Bedrock and Polly credentials remain on the local side. The MicroVM receives validated plans and
state proposals, not AWS credentials. Presentation clients consume structured `OpeningView`,
`GameSnapshot`, `TurnView`, and `UsageSnapshot` values, so a future web client can reuse the same
game orchestration without importing Textual or parsing terminal output.

See [Architecture](docs/architecture.md), [RFC 0001](docs/rfcs/0001-web-control-plane.md), the
[web control plane plan](docs/plans/web-control-plane.md), and [Security](docs/security.md) for the
detailed design and next implementation phase.

## Requirements

- Python 3.14
- [uv](https://docs.astral.sh/uv/)
- AWS CLI v2 with Lambda MicroVM commands
- An AWS profile with access to Lambda MicroVMs, Amazon Bedrock, and Amazon Polly
- Access to the configured Bedrock model; Claude Sonnet 4.6 is the working default
- macOS or Linux for the current local audio adapters

Docker with ARM64 support is needed only when building the image locally.

## Play

Install all local dependencies:

```sh
git clone https://github.com/DavidCs9/lambda-microvm-dungeon-agent.git
cd lambda-microvm-dungeon-agent
uv sync --all-groups
```

Get the latest active image version, then launch the TUI:

```sh
IMAGE_ARN="arn:aws:lambda:us-east-2:225989371926:microvm-image:dungeon-agent-fastapi"
IMAGE_VERSION="$(aws lambda-microvms get-microvm-image \
  --profile personal \
  --region us-east-2 \
  --image-identifier "$IMAGE_ARN" \
  --query latestActiveImageVersion \
  --output text)"

uv run --group tooling dungeon-agent \
  --profile personal \
  --region us-east-2 \
  --image-arn "$IMAGE_ARN" \
  --image-version "$IMAGE_VERSION"
```

This resolves the active version at launch instead of hardcoding a version that becomes stale.
Use `--language es` or `--language en` to skip language selection. Use `--plain` for a basic
terminal, CI smoke test, or redirected input.

Choose another available model without changing code:

```sh
uv run --group tooling dungeon-agent <the same AWS arguments> \
  --model-id us.anthropic.claude-sonnet-5
```

Sonnet 5 currently requires account access from AWS; Sonnet 4.6 remains the default until that
access is granted.

### Controls

| Input | Action |
|---|---|
| Any sentence | Attempt that action in the fiction |
| `F1` or `/help` | Show localized help |
| `F2` or `/state` | Refresh game state |
| `F3` or `/stats` | Refresh model usage and cost |
| `F4` | Toggle Dungeon Master voice |
| `F5` | Toggle ambience |
| `Ctrl+Q` or `/quit` | Terminate the MicroVM and exit |

Audio is a local presentation adapter. The game remains fully playable with `--no-voice` and
`--no-music`. Cached audio is written under `dist/audio-cache`; privacy-safe session metrics are
appended to `dist/session-metrics.jsonl`.

## Development

```sh
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python evals/gameplay_experience.py
```

The deterministic gameplay eval checks roleplay context persistence, d20 branching, creative state
progress, authoritative terminal conditions, and state consistency. Compare actual Bedrock models
as world architect, character architect, and Dungeon Master in both official languages:

```sh
uv run --group tooling python evals/narration_models.py \
  --profile personal \
  --region us-east-2 \
  --model-id us.anthropic.claude-sonnet-4-6
```

Run the FastAPI rules service without a MicroVM:

```sh
DUNGEON_WORKSPACE_DIR="$(mktemp -d)" \
  uv run uvicorn dungeon_agent.api.main:app --reload
```

The service exposes health and state at `/health` and `/v1/world`; interactive OpenAPI docs are at
`/docs`. Starting a game requires both a validated `AdventurePlan` and `PlayerCharacter`.

## Repository structure

- `src/dungeon_agent/api/` — FastAPI rules and persistent state inside the MicroVM
- `src/dungeon_agent/domain/` — framework-neutral game and presentation contracts
- `src/dungeon_agent/control_plane/domain/` — versioned web session contracts and ports
- `src/dungeon_agent/orchestrator/` — agents, game use cases, contracts, and MicroVM adapter
- `src/dungeon_agent/tui/` — Textual presentation layer
- `src/dungeon_agent/audio/` — local voice, ambience, and dice adapters
- `src/dungeon_agent/operations/` — image and benchmark workflows
- `src/dungeon_agent/resources/` — packaged locales and reviewed model pricing
- `evals/` — deterministic and live model-quality evaluations
- `tests/` — API, orchestration, presentation, audio, and persistence tests
- `infra/` — CloudFormation bootstrap and GitHub OIDC release infrastructure
- `scripts/` — small operational entry points only

## Images, CI, and releases

Normal pushes and pull requests do not authenticate to AWS. CI runs formatting, linting, strict
typing, tests, gameplay evals, deterministic source packaging, and an ARM64 container build.

Tags matching `v*` trigger the release workflow. It repeats the quality gates, assumes a short-lived
AWS role through GitHub OIDC, publishes a new version of `dungeon-agent-fastapi`, and creates a
GitHub Release with image metadata. Builds and AWS publication are intentionally separate.

For one-time release infrastructure setup, see [infra/README.md](infra/README.md). To package or
publish manually, use `python -m scripts.build_microvm_image`; to measure launch, suspend, resume,
and warm-request latency, use `python -m scripts.benchmark_microvm`.

## Safety and project status

This is an experimental public lab, not a production service. Do not add generated-code execution
without restricted network egress, resource limits, and a dedicated security review. Never commit
AWS credentials, MicroVM auth tokens, `.env` files, generated session state, or private source
material.

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) first.

## License

MIT

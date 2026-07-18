# Lambda MicroVM Dungeon Agent

A small, stateful AI-agent lab for testing AWS Lambda MicroVM isolation, authenticated HTTPS connectivity, and suspend/resume state preservation.

[![CI](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Status

The project is a playable bilingual terminal game. Every session gets a newly generated fantasy
one-shot, while a validated rules service inside a dedicated MicroVM protects game state. A
separate web client can reuse the same presentation-neutral orchestration contract later.

## Prerequisites

- Python 3.14
- [uv](https://docs.astral.sh/uv/)
- Docker with ARM64 build support
- AWS CLI with Lambda MicroVM support
- An AWS account able to create lab-scoped resources in `us-east-2`

## Local development

```sh
uv sync
uv run pytest
DUNGEON_WORKSPACE_DIR="$(mktemp -d)" uv run uvicorn dungeon_agent.api.main:app --reload
```

The backend needs a generated `AdventurePlan` before it accepts turns. The easiest complete
experience is the CLI described below; API examples are available through `/docs` while running.

```sh
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/world
open http://127.0.0.1:8000/docs
```

## Repository layout

- `src/dungeon_agent/api/` — FastAPI application hosted inside the MicroVM
- `src/dungeon_agent/orchestrator/` — generated-adventure agents, presentation-neutral game loop, and session lifecycle
- `src/dungeon_agent/tui/` — Textual terminal presentation client and styling
- `src/dungeon_agent/cli.py` — installed player CLI and dependency composition
- `tests/` — API and persistence tests
- `docs/` — architecture and security decisions
- `infra/` — secure CloudFormation bootstrap resources
- `scripts/` — small operational image-build and benchmark entrypoints

## Build a Lambda MicroVM image

Authenticate with a short-lived AWS profile, then bootstrap the private artifact bucket and least-privilege build role:

```sh
AWS_PROFILE=personal AWS_REGION=us-east-2 aws cloudformation deploy \
  --stack-name lambda-microvm-dungeon-agent-bootstrap \
  --template-file infra/bootstrap.yaml \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset
```

Package the backend deterministically, upload it to S3, and create the snapshot-backed image:

```sh
uv run --group tooling python -m scripts.build_microvm_image \
  --profile personal \
  --region us-east-2
```

The command creates the image when it does not exist and publishes a new version otherwise. It
prints the artifact digest, S3 URI, image ARN, and active image version. It does not launch a
billable MicroVM.

## CI and versioned AWS releases

Normal pushes and pull requests never authenticate to AWS. CI runs the quality gates, builds the
ARM64 container, and uploads a deterministic source bundle as a short-lived workflow artifact.

Tags matching `v*` trigger `.github/workflows/release.yml`. That workflow verifies and packages
the tagged commit, obtains short-lived AWS credentials through GitHub OIDC, publishes a new
version of `dungeon-agent-fastapi`, and creates a GitHub Release containing the source bundle and
image metadata.

The one-time OIDC role setup is documented in `infra/README.md`. Configure these variables on the
GitHub `release` environment:

- `AWS_RELEASE_ROLE_ARN`
- `AWS_REGION` (`us-east-2`)
- `AWS_BOOTSTRAP_STACK` (`lambda-microvm-dungeon-agent-bootstrap`)

Publish a version only when intended:

```sh
git tag -a v0.2.0 -m "Dungeon Agent release"
git push origin v0.2.0
```

## Run the lifecycle and latency lab

Launch an authenticated MicroVM, exercise the FastAPI API, suspend and resume it, verify state preservation, and terminate it in a guaranteed cleanup path:

```sh
uv run --group tooling python -m scripts.benchmark_microvm \
  --profile personal \
  --region us-east-2 \
  --image-arn <microvm-image-arn> \
  --image-version <microvm-image-version>
```

The harness prints launch, warm request, suspend, resume, and post-resume latency measurements as JSON. Lambda MicroVMs use public internet egress by default; do not enable agent-generated code execution until a restricted VPC egress connector is configured.

## Play through the master orchestrator

The orchestrator launches one MicroVM session, asks Claude to design a fresh one-shot, and starts
that validated plan inside the MicroVM. For every free-form player action, Claude returns typed
success and failure branches; the MicroVM rolls the d20, validates all proposed changes, applies
one branch, and remains the authority on victory and defeat.

```sh
uv run --group tooling dungeon-agent \
  --profile personal \
  --region us-east-2 \
  --image-arn <microvm-image-arn> \
  --image-version <microvm-image-version>
```

The CLI opens a full-screen TUI with language selection, connection progress, a wrapped story
transcript, command input, current world state, session usage, and keyboard shortcuts:

- `F1` — show localized help and action examples
- `F2` — refresh current state
- `F3` — refresh token usage, latency, and estimated cost
- `F4` — toggle Dungeon Master voice
- `F5` — toggle original fantasy ambience
- `Ctrl+Q` — terminate the MicroVM and exit

The following typed commands work in both the TUI and plain interface:

- `/help` — show instructions and action examples
- `/state` — show location, inventory, and turn count
- `/stats` — show model calls, token usage, latency, and estimated session cost
- `/quit` — terminate the MicroVM and exit

### Voice and ambience

The TUI speaks Dungeon Master narration with Amazon Polly, plays quiet original fantasy ambience,
and gives every d20 roll its own locally generated dice sound. Rolls also appear in a prominent
success/failure panel. Audio is a presentation adapter: it runs on the player's computer and is
not part of the MicroVM image or game rules.

- `F4` — toggle Dungeon Master voice
- `F5` — toggle ambience
- `--no-voice` — start without Polly speech
- `--no-music` — start without ambience
- `--polly-region` — select the Polly region (default: `us-east-1`)
- `--audio-cache` — select the local generated-audio cache (default: `dist/audio-cache`)

English uses Polly's Matthew voice and Spanish uses the Mexican Spanish Andrés voice with the
generative engine. The AWS identity running the local CLI needs `polly:SynthesizeSpeech`.
Gameplay remains fully functional if audio is disabled or the host has no supported player.

Ctrl+C also terminates the session cleanly. Add `--plain` for the stream-based interface used by
basic terminals and debugging. A non-interactive `--turn "Look around"` run automatically uses
plain mode. Bedrock calls use required typed tools and explicit output limits: 3,000 tokens for
one-time adventure design and 1,200 tokens per turn.

Claude Sonnet 4.6 is the working default. Sonnet 5 can be selected without code changes once the
AWS account has model access:

```sh
play-dungeon --model-id us.anthropic.claude-sonnet-5
```

Presentation clients depend on `GamePort`, which exposes structured `GameSnapshot`, `TurnView`,
and `UsageSnapshot` values. AWS client construction and metrics persistence remain in the CLI
composition root. A future web client can therefore reuse the orchestration layer without
importing Textual or parsing terminal-formatted strings.

Each completed or failed CLI session appends privacy-safe LLM telemetry to
`dist/session-metrics.jsonl`. Override the path with `--metrics-output`. Records include the
session ID, model, calls, input/output tokens, aggregate model latency, and estimated USD cost;
they never include prompts, player actions, narration, endpoints, or authentication tokens.
Pricing is loaded from `src/dungeon_agent/resources/model_pricing.json` so it can be reviewed and
updated independently of Python code.

### Languages

Before launching the MicroVM, the CLI asks the player to choose an official language:

1. Español
2. English

The choice asks the architect and DM to create all session-specific content in that language and
localizes commands, prompts, state, errors, and shutdown messages. Press Enter to choose Español,
or skip the menu with `--language es` or `--language en`.

Presentation language lives in packaged JSON resources under `src/dungeon_agent/resources/locales/`.
Adding a language does not require embedding translated UI text in Python code.

## Gameplay evaluation

Run the deterministic generated-world safety evaluation:

```sh
uv run python evals/gameplay_experience.py
```

It checks d20 resolution, terminal conditions, state consistency, and rejection of model-proposed
unknown locations and items. Model selection is evaluated separately on identical English and
Spanish adventure tasks.

```sh
uv run --group tooling python evals/narration_models.py \
  --profile personal \
  --region us-east-2 \
  --model-id us.anthropic.claude-sonnet-4-6
```

## Planned milestones

1. Validate the FastAPI backend and ARM64 container.
2. Bootstrap the build resources and create the MicroVM image in Ohio (`us-east-2`).
3. Add lifecycle hooks and restricted VPC egress.
4. Automate repeatable benchmark result capture.
5. Add a constrained code-execution tool inside the MicroVM.
6. Connect an AI model and run the dungeon experiment.

## Safety

Read `docs/security.md` before enabling generated-code execution. Never commit `.env` files, AWS credentials, auth tokens, build artifacts, or generated session state.

## Contributing

Contributions are welcome. See `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md` before opening an issue or pull request.

## License

MIT

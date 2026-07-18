# Lambda MicroVM Dungeon Agent

A small, stateful AI-agent lab for testing AWS Lambda MicroVM isolation, authenticated HTTPS connectivity, and suspend/resume state preservation.

[![CI](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Status

The repository currently contains a FastAPI backend and tests. AWS deployment and arbitrary code execution are intentionally not enabled yet. A separate web client may be added later; this repository currently focuses on the backend API.

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

In another terminal:

```sh
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/world
curl -X POST http://127.0.0.1:8000/v1/actions \
  -H 'content-type: application/json' \
  -d '{"action":"Open the snapshot door"}'
```

## Repository layout

- `src/dungeon_agent/api/` — FastAPI application hosted inside the MicroVM
- `src/dungeon_agent/orchestrator/` — game loop, localization, narration, and session lifecycle
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
git tag -a v0.2.0 -m "Snapshot Tavern one-shot"
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

The orchestrator launches one MicroVM session, persists each player action in the FastAPI backend, uses Amazon Bedrock Nova Micro for narration, and terminates the MicroVM on exit:

```sh
uv run --group tooling dungeon-agent \
  --profile personal \
  --region us-east-2 \
  --image-arn <microvm-image-arn> \
  --image-version <microvm-image-version>
```

The CLI opens with a narrated scene, example actions, and visible controls:

- `/help` — show instructions and action examples
- `/state` — show location, inventory, and turn count
- `/quit` — terminate the MicroVM and exit

Ctrl+C also terminates the session cleanly. For a non-interactive smoke test, add `--turn "Inspect the humming machine"`. The Bedrock Converse request explicitly caps output at 180 tokens per turn.

### Languages

Before launching the MicroVM, the CLI asks the player to choose an official language:

1. Español
2. English

The choice localizes the opening scene, narration, commands, prompts, state, errors, and shutdown messages. Press Enter to choose Español, or skip the menu with `--language es` or `--language en`.

Language content and action vocabulary live in packaged JSON resources under
`src/dungeon_agent/resources/locales/`. Adding a language does not require embedding translated
game text in Python code.

## Gameplay evaluation

Run the deterministic black-box gameplay evaluation:

```sh
uv run python evals/gameplay_experience.py
```

It checks player agency, guidance, danger, state consistency, and structured world depth across
multiple playthroughs. Model selection is evaluated separately so narration cannot hide weak game
rules. Compare one or more Bedrock models on identical English and Spanish scenes:

```sh
uv run --group tooling python evals/narration_models.py \
  --profile personal \
  --region us-east-2 \
  --model-id us.amazon.nova-micro-v1:0
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

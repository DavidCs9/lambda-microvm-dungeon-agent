# Lambda MicroVM Dungeon Agent

A small, stateful AI-agent lab for testing AWS Lambda MicroVM isolation, authenticated HTTPS connectivity, and suspend/resume state preservation.

[![CI](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Status

The repository currently contains a FastAPI backend and tests. AWS deployment and arbitrary code execution are intentionally not enabled yet. A separate web client may be added later; this repository currently focuses on the backend API.

## Prerequisites

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Docker with ARM64 build support
- AWS CLI with Lambda MicroVM support
- An AWS account able to create lab-scoped resources in `us-east-2`

## Local development

```sh
uv sync
uv run pytest
DUNGEON_WORKSPACE_DIR="$(mktemp -d)" uv run uvicorn app.main:app --reload
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

- `app/` — FastAPI application, settings, schemas, and state store
- `tests/` — API and persistence tests
- `docs/` — architecture and security decisions
- `infra/` — secure CloudFormation bootstrap resources
- `scripts/` — typed packaging and MicroVM image build tooling

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
uv run --group tooling python -m scripts.microvm_image \
  --profile personal \
  --region us-east-2
```

The command prints the local artifact path, SHA-256 digest, S3 URI, and MicroVM image ARN. It waits for the image to reach `CREATED` unless `--no-wait` is provided. It does not launch a billable MicroVM.

## Run the lifecycle and latency lab

Launch an authenticated MicroVM, exercise the FastAPI API, suspend and resume it, verify state preservation, and terminate it in a guaranteed cleanup path:

```sh
uv run --group tooling python -m scripts.microvm_session \
  --profile personal \
  --region us-east-2 \
  --image-arn <microvm-image-arn>
```

The harness prints launch, warm request, suspend, resume, and post-resume latency measurements as JSON. Lambda MicroVMs use public internet egress by default; do not enable agent-generated code execution until a restricted VPC egress connector is configured.

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

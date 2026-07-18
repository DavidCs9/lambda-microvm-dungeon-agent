# Lambda MicroVM Dungeon Agent

A small, stateful AI-agent lab for testing AWS Lambda MicroVM isolation, authenticated HTTPS connectivity, and suspend/resume state preservation.

[![CI](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Status

The repository currently contains a dependency-free sandbox API and tests. AWS deployment and arbitrary code execution are intentionally not enabled yet.

## Prerequisites

- Node.js 24 (Node.js 20 also works for current local tests)
- Docker with ARM64 build support
- AWS CLI with Lambda MicroVM support
- An AWS account able to create lab-scoped resources in `us-east-2`

## Local development

```sh
nvm use
npm test
WORKSPACE_DIR="$(mktemp -d)" npm start
```

In another terminal:

```sh
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/state
curl -X POST http://127.0.0.1:8080/action \
  -H 'content-type: application/json' \
  -d '{"action":"Open the snapshot door"}'
```

## Repository layout

- `src/` — MicroVM HTTP application and state store
- `test/` — dependency-free Node test suite
- `docs/` — architecture and security decisions
- `infra/` — deployment automation placeholder
- `scripts/` — future build, benchmark, and cleanup helpers

## Planned milestones

1. Validate the local API and ARM64 container.
2. Add repeatable AWS bootstrap and cleanup automation.
3. Create and launch the MicroVM image in Ohio (`us-east-2`).
4. Measure launch, warm-request, suspend, and resume latency.
5. Add a constrained code-execution tool inside the MicroVM.
6. Connect an AI model and run the dungeon experiment.

## Safety

Read `docs/security.md` before enabling generated-code execution. Never commit `.env` files, AWS credentials, auth tokens, build artifacts, or generated session state.

## Contributing

Contributions are welcome. See `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md` before opening an issue or pull request.

## License

MIT

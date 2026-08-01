# Lambda MicroVM Dungeon Agent

> **Personal lab — not production code.**
>
> This repo is a one-dev sandbox for experimentation and learning. It is **not** a product, **not**
> a sample of how I write production systems, and **not** a claim that a dungeon game needs this
> much architecture.
>
> Parts of the design are deliberately overbuilt so I can practice real concepts hands-on — control
> plane vs data plane, Lambda MicroVMs, SAM deploy lanes, Bedrock agents, and so on. I also
> vibe-code here on purpose: exploring AI-assisted coding and training my own judgment of what the
> tools get right and wrong.
>
> If you're a recruiter or another engineer browsing: read the curiosity and the experiments, not
> the ceremony. For how I'd ship something for real users, ask me — this isn't that.

An AI one-shot RPG where a browser client talks to a sandbox AWS backend. Campaigns generate a
world and protagonist once; each play session forks that campaign into an isolated Lambda MicroVM
that owns dice and world mutations.

[![CI](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidCs9/lambda-microvm-dungeon-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## How this started

Weekend experiment to poke AWS Lambda MicroVMs: launch an isolated VM, hit a small FastAPI guest
over authenticated HTTPS, keep state across the lifecycle, measure latency. A tiny dungeon made
the infra test less boring. The dungeon was fun, so the lab grew into campaigns, a web client,
Bedrock architects, Polly narration, and deploy lanes — plus some intentional over-engineering so
the infra lessons stuck. Still one-dev, still a lab.

## What you play

1. **Create a campaign** — Adventure Architect + Character Architect (Bedrock) build a world and
   protagonist once. Optional portrait. No MicroVM.
2. **Start a session** — fork the ready campaign into a dedicated MicroVM; zero model calls on the
   play-boot path.
3. **Act freely** — the Dungeon Master proposes outcomes; the MicroVM rolls the d20, validates,
   persists, and decides win/lose.
4. **Hear it** — Polly speech (data plane) for narration when configured.

Spanish is the showcase UI language; generation supports Spanish and English.

## Architecture (C4)

Full write-up, L3 planes, and sequences: [docs/architecture.md](docs/architecture.md).

### L1 — System context

Player browser → Dungeon Agent → Bedrock (LLMs/images) and Lambda MicroVMs (isolated game host).

![L1 System Context](docs/diagrams/l1-system-context.png)

### L2 — Containers

Deployable units inside the system boundary. The browser never talks to the MicroVM.

![L2 Containers](docs/diagrams/l2-containers.png)

| Container | Role |
|---|---|
| **Web SPA** | React/Vite showcase UI |
| **Backend** | One SAM stack: API Gateway HTTP + WebSocket, Lambdas, Step Functions |
| **Session store** | DynamoDB: campaigns, sessions, events, snapshots |
| **Game MicroVM** | FastAPI guest: dice, validate/apply world, no AWS credentials |

Inside the Backend package split (same deploy): **control plane** sets up campaigns/sessions;
**data plane** runs turns and speech; **plane_shared** holds contracts, DynamoDB, WS delivery, and
the MicroVM HTTP client. Details and more diagrams in the architecture doc.

## Play (web)

Needs a deployed sandbox stack (`dungeon-agent-control-plane-sandbox` in `us-east-2`) and a current
MicroVM image the stack can launch. Stack deploy: [infra/README.md](infra/README.md) and
[infra/control-plane/workflow/README.md](infra/control-plane/workflow/README.md).

```sh
cd web
cp .env.example .env.local
# Set VITE_HTTP_URL / VITE_WS_URL from CloudFormation outputs ApiUrl / WebSocketUrl
npm install
npm run dev
```

Sandbox auth is `x-player-id` / WebSocket `playerId` (not Cognito). Lab convenience only.

## Local MicroVM smoke (optional)

The Textual TUI / plain CLI still launch a one-shot session against a MicroVM for infra smoke tests.
That path is not the web play loop.

```sh
uv sync --all-groups
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

Use `--language es|en`, `--plain`, `--no-voice`, `--no-music` as needed.

## Development

```sh
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python evals/gameplay_experience.py
```

Frontend: `cd web && npm run build` (or `npm run dev` against the sandbox API).

Guest FastAPI without a MicroVM:

```sh
DUNGEON_WORKSPACE_DIR="$(mktemp -d)" \
  uv run uvicorn dungeon_agent.api.main:app --reload
```

## Repository map

- `web/` — showcase SPA
- `src/dungeon_agent/control_plane/` — campaign/session lifecycle, workflows, composition root
- `src/dungeon_agent/data_plane/` — turns, speech, live play events
- `src/dungeon_agent/plane_shared/` — HTTP/WS edge, DynamoDB, contracts, MicroVM client
- `src/dungeon_agent/api/` — FastAPI rules/state inside the MicroVM
- `src/dungeon_agent/domain/` — game schemas
- `src/dungeon_agent/orchestrator/`, `tui/`, `cli.py` — local smoke path
- `src/dungeon_agent/operations/` — image build and benchmarks
- `infra/` — bootstrap, OIDC release role, SAM control-plane stack
- `docs/` — architecture (C4), RFCs, security
- `evals/`, `tests/`, `scripts/`

## CI and releases

PRs run path-filtered lanes (see [`.cursor/rules/deploy-lanes.mdc`](.cursor/rules/deploy-lanes.mdc)):

- `web/**` → frontend build
- control-plane / Python → ruff, mypy, pytest, gameplay evals
- MicroVM image paths → also ARM64 container build + source package

The aggregating **CI** check always reports. Tags `v*` publish a new `dungeon-agent-fastapi`
MicroVM image via GitHub OIDC. Manual image/benchmark entrypoints:
`python -m scripts.build_microvm_image`, `python -m scripts.benchmark_microvm`.

## Status

Personal experimental lab — see the disclaimer at the top. Not a production service. Do not add
generated-code execution without egress limits and a dedicated security look. Never commit
credentials, MicroVM tokens, `.env`, or session state.

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

MIT

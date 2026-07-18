# Web Control Plane Implementation Plan

This plan implements [RFC 0001](../rfcs/0001-web-control-plane.md) through small vertical slices.
Each slice must be independently testable, deployable, and revertible. A slice is not complete
until its acceptance criteria and observability are present.

## Principles

- Build one end-to-end path before expanding resource coverage.
- Keep domain contracts independent of Lambda, API Gateway, and browser frameworks.
- Add infrastructure through reviewed IaC; do not create production resources manually.
- Prefer idempotent handlers and conditional writes from the first version.
- Store events before attempting WebSocket delivery.
- Capture latency baselines before optimizing or moving compute to ECS.

## Parallel execution model

Implementation uses one short sequential foundation followed by parallel workstreams. Agents must
not begin infrastructure or adapters by inventing their own payloads. The contract foundation is a
merge barrier: it lands first, and every later branch builds against the same versioned schemas and
ports.

```text
Foundation: contracts and boundaries
                    |
        +-----------+-----------+----------------+
        |           |           |                |
   Persistence   HTTP API   Workflow shell   Agent extraction
        |           |           |                |
        +-----------+-----------+----------------+
                    |
             Integration checkpoint
                    |
        +-----------+-----------+----------------+
        |           |           |                |
   WebSockets    Web UI    MicroVM manager   Live agent steps
        |           |           |                |
        +-----------+-----------+----------------+
                    |
          End-to-end session creation
                    |
        +-----------+-----------+----------------+
        |           |           |                |
    Turn path     Audio      Streaming lab   Operations
```

### Merge and ownership rules

Each parallel work package owns a narrow path. Shared-contract changes require a small dedicated
contract commit before dependent branches continue.

| Workstream | Primary ownership | Avoid editing |
|---|---|---|
| Contracts | `src/dungeon_agent/control_plane/domain/` | AWS adapters and web assets |
| Persistence | `src/dungeon_agent/control_plane/persistence/` | HTTP and WebSocket handlers |
| HTTP API | `src/dungeon_agent/control_plane/http/` | repository implementations |
| Workflow | `infra/control-plane/workflow/` | agent business logic |
| Agent adapters | `src/dungeon_agent/control_plane/agents/` | API handlers and frontend |
| MicroVM manager | `src/dungeon_agent/control_plane/microvms/` | model adapters |
| WebSocket | `src/dungeon_agent/control_plane/realtime/` | HTTP handlers and frontend views |
| Web client | `web/` | Python backend implementation |
| Observability | `src/dungeon_agent/control_plane/telemetry/` | domain contracts |
| IaC composition | `infra/control-plane/` composition files | application internals |

Tests should live beside the owned adapter's test module. Cross-workstream end-to-end tests belong
to an integration owner and are added only after the relevant branches merge.

## Execution waves

### Wave 0: Contract foundation — sequential merge barrier

Only this wave is intentionally sequential. Complete Slice 0 and merge it before launching the
first parallel group.

Status: completed on 2026-07-18. The foundation lives in `src/dungeon_agent/domain/` and
`src/dungeon_agent/control_plane/domain/`, with bilingual transport fixtures under
`tests/fixtures/control_plane/`.

Required outputs:

- versioned session, event, opening, workflow-input, and error schemas;
- application ports for sessions, events, agents, MicroVMs, and event delivery;
- lifecycle and phase state machines as domain enums;
- idempotency and revision semantics;
- example fixtures in English and Spanish;
- import-boundary tests.

The foundation must not contain boto3, Lambda event shapes, API Gateway objects, Step Functions
payload logic, Textual, or a frontend framework.

### Wave 1: Four independent foundations

Start these work packages in parallel after Wave 0:

| Package | Scope | Depends on | Integration output |
|---|---|---|---|
| W1-A Persistence | Slice 1 | Wave 0 | in-memory and DynamoDB repositories |
| W1-B HTTP control plane | Slice 2 using repository fakes | Wave 0 | authenticated route handlers |
| W1-C Workflow skeleton | Slice 3 using stub tasks | Wave 0 | deployable Standard state machine |
| W1-D Agent extraction | shared extraction needed by Slices 4 and 5 | Wave 0 | framework-neutral agent ports/adapters |

W1-B must depend on repository ports, not the DynamoDB implementation. W1-C must invoke task
contracts, not import the actual agents. This keeps all four branches independently testable.

### Integration checkpoint 1

Merge Wave 1 and execute one stubbed vertical path:

```text
POST /sessions -> DynamoDB -> Step Functions stub -> persisted events -> GET replay
```

No Bedrock or MicroVM call is required. Do not begin full end-to-end assembly until duplicate
creation, ownership, workflow failure, and event sequencing tests pass here.

### Wave 2: Product capabilities in parallel

Launch these after Integration checkpoint 1:

| Package | Scope | Depends on | Can run with |
|---|---|---|---|
| W2-A Adventure step | Slice 4 | W1-C, W1-D | all Wave 2 packages |
| W2-B Character step | Slice 5; use adventure fixtures first | W1-D | all Wave 2 packages |
| W2-C MicroVM manager | Slice 6 | W1-C | all Wave 2 packages |
| W2-D WebSocket/replay | Slice 7 | W1-A | all Wave 2 packages |
| W2-E Minimal web shell | Slice 8 against a mock server | Wave 0 event schemas | all Wave 2 packages |
| W2-F Telemetry foundation | metric contracts and dashboards-as-code skeleton | Wave 0 | all Wave 2 packages |

The Character step must be developed against a committed `AdventurePlan` fixture so it does not
wait for W2-A. The web client uses recorded event fixtures and a mock transport so it does not wait
for deployed APIs. The MicroVM manager uses a fake lifecycle client in tests so it does not wait for
a newly published image.

### Integration checkpoint 2

Merge Wave 2 behind feature flags and validate session creation end to end:

```text
Browser -> HTTP create -> workflow -> Adventure -> Character -> MicroVM -> WebSocket ready
```

This checkpoint establishes real phase latency and verifies reconnect/replay. It is the first point
where all AWS resources must work together.

### Wave 3: Interactive game capabilities in parallel

After session creation is stable, launch:

| Package | Scope | Depends on |
|---|---|---|
| W3-A Authoritative turn path | Slice 9 | checkpoint 2 |
| W3-B Synchronized audio | Slice 10 | opening block contracts and web shell |
| W3-C Streaming experiment | Slice 11 using recorded authoritative outcomes | realtime transport |
| W3-D Operations baseline | first half of Slice 12 | deployed checkpoint 2 resources |
| W3-E Rehydration tests | resume subset of Slice 9 | persistence and MicroVM manager |

The streaming experiment must consume recorded resolved turns until W3-A is integrated. Audio can
use static opening fixtures. Operations work can instrument setup workflows before turns exist.

### Integration checkpoint 3

Combine one complete action, synchronized audio, and optional streaming. Run the gameplay eval and
a real browser playtest before choosing the default narration path.

### Wave 4: Hardening

Complete Slice 12 in parallel by concern: security review, load testing, cost controls, alarms, and
runbooks. Public access remains blocked until their shared release checklist passes.

## Parallel task sizing

Each assigned package should target one reviewable commit and approximately one coherent adapter
or use case. If a package needs changes in more than two ownership areas, split the contract or
integration work first. Good agent-sized tasks include:

- define and test the DynamoDB session repository;
- implement the create-session HTTP handler against a fake repository;
- author the stub Standard state machine and failure path;
- extract `CharacterArchitect` behind its port;
- implement WebSocket connection persistence and stale-connection cleanup;
- build the web progress screen against recorded events;
- add phase-level embedded metrics without changing business logic.

Avoid assigning “build the control plane,” “build the website,” or “implement Step Functions” as a
single task. Those scopes cross contracts, infrastructure, application logic, and integration.

## Slice 0: Repository boundaries and contracts

Deliverables:

- Add packages for control-plane domain, application use cases, and AWS adapters.
- Move shared session, opening, turn, and event schemas into presentation-neutral contracts.
- Define versioned `SessionEvent` and session lifecycle values.
- Add architecture tests that prevent control-plane domain code from importing AWS or Textual.
- Mark the TUI frozen in project documentation; allow only critical compatibility fixes.

Acceptance criteria:

- Existing TUI and MicroVM tests remain green.
- Contracts serialize deterministically and validate English and Spanish examples.
- No deployed resources are introduced.

Parallelization: none. This is the shared merge barrier for every later workstream.

## Slice 1: Session persistence

Deliverables:

- Define a DynamoDB single-table access pattern for sessions, events, idempotency, and connections.
- Implement repository ports plus an in-memory adapter for unit tests.
- Implement the DynamoDB adapter with conditional writes and monotonic event sequences.
- Add session creation, status lookup, and event replay use cases.
- Add TTL only to ephemeral connection and idempotency records.

Acceptance criteria:

- Duplicate create requests return the same session.
- Concurrent event appends cannot produce duplicate sequence numbers.
- Events can be replayed after a known sequence.
- Repository tests run locally without AWS.

Parallelization: Wave 1 package W1-A. It can proceed alongside HTTP, workflow, and agent extraction.

## Slice 2: Minimal HTTP control plane

Deliverables:

- Add API Gateway HTTP API routes:
  - `POST /sessions`
  - `GET /sessions/{sessionId}`
  - `GET /sessions/{sessionId}/events`
- Add JWT authentication and ownership checks.
- Return `202 Accepted` for creation.
- Start a placeholder workflow using `sessionId` as the idempotent execution name.
- Add structured error envelopes and correlation IDs.

Acceptance criteria:

- The create route responds in under two seconds without waiting for generation.
- Unauthorized cross-user reads fail.
- Repeated idempotent requests do not start duplicate executions.
- API logs exclude request prose and credentials.

Parallelization: Wave 1 package W1-B. Develop against repository fakes.

## Slice 3: Step Functions session skeleton

Deliverables:

- Create a Step Functions Standard state machine in IaC.
- Implement phase events, explicit task timeouts, bounded retries, and a terminal failure path.
- Use stub agent tasks to exercise the complete state order.
- Store workflow ARN and phase timestamps on the session.
- Route failed, timed-out, and aborted executions to operational monitoring.

Acceptance criteria:

- The visual execution history shows every named phase.
- A forced task failure marks the session failed and persists an error event.
- Retriable faults use backoff and jitter; validation faults do not retry.
- Per-phase and total setup latency are queryable.

Parallelization: Wave 1 package W1-C. Develop against stub task Lambdas.

## Slice 4: Real Adventure Architect step

Deliverables:

- Extract Adventure Architect behind a control-plane application port.
- Implement its Lambda adapter with Bedrock Converse and required structured output.
- Persist the validated `AdventurePlan` outside Step Functions payload state.
- Capture model ID, tokens, latency, repair count, and error category.
- Add contract and live opt-in evals.

Acceptance criteria:

- English and Spanish plans pass the existing generated-world validators.
- Invalid structured output repairs at most once.
- Secrets are never included in player-facing events.
- Metrics identify this agent independently.

Parallelization: Wave 2 package W2-A.

## Slice 5: Real Character Architect step

Deliverables:

- Extract Character Architect behind its own application port.
- Load the persisted adventure and create `PlayerCharacter` in a separate Lambda task.
- Persist character and ordered opening blocks.
- Extend evals for viewpoint consistency, singular/plural agreement, roleplay potential, spoiler
  avoidance, and actionable starting choices.
- Emit a character-ready phase without sending private world secrets.

Acceptance criteria:

- The character has a playable connection to the generated adventure.
- Opening grammar and viewpoint agree with one protagonist.
- The same opening blocks are usable by visual and audio adapters.
- Agent metrics remain separate from world-generation metrics.

Parallelization: Wave 2 package W2-B. Use committed adventure fixtures instead of waiting for W2-A.

## Slice 6: MicroVM lifecycle and initialization

Deliverables:

- Add a least-privilege MicroVM manager Lambda.
- Launch, poll, authenticate, initialize, and terminate MicroVMs through explicit workflow states.
- Persist the active `microvmId`, image version, state revision, and safe rehydration metadata.
- Add cleanup for partially created sessions.
- Measure launch, readiness, initialization, and termination independently.

Acceptance criteria:

- A generated session becomes ready in a versioned MicroVM.
- Failed workflows do not leak active MicroVMs.
- Model Lambdas cannot manage MicroVMs.
- Auth tokens never enter workflow history, DynamoDB, or normal logs.

Parallelization: Wave 2 package W2-C.

## Slice 7: WebSocket progress and replay

Deliverables:

- Add API Gateway WebSocket routes for connect, disconnect, subscribe, and ping.
- Store connection records with TTL.
- Implement durable event append followed by best-effort delivery.
- Remove stale connections on gone responses.
- Add browser reconnection and HTTP event replay.

Acceptance criteria:

- A browser sees every setup phase in order.
- Disconnecting during generation does not lose events.
- Reconnection resumes after the last acknowledged sequence.
- Initial progress appears within two seconds of session creation.

Parallelization: Wave 2 package W2-D.

## Slice 8: Minimal web experience

Deliverables:

- Add a small web client with login, language selection, new session, progress, briefing, and one
  action input.
- Render setup phases with elapsed time and truthful status messages.
- Render ordered opening blocks rather than one unstructured paragraph.
- Add responsive loading, error, retry, reconnecting, ready, and completed states.
- Keep frontend state derived from server snapshots and ordered events.

Acceptance criteria:

- A new player can understand who they are, what they want, where they are, and three ways to act.
- Refreshing the page restores the session.
- The client never invents completion for a server phase.
- Mobile and desktop layouts remain usable.

Parallelization: Wave 2 package W2-E. Develop with recorded event fixtures and a mock transport.

## Slice 9: Authoritative turn path

Deliverables:

- Add idempotent player-action submission with expected session revision.
- Run the Dungeon Master adapter, authoritative MicroVM application, durable event append, and
  snapshot persistence.
- Emit `turn.started`, `dice.rolled`, and `turn.completed` events.
- Reject concurrent or stale actions predictably.
- Rehydrate an inactive session into a new MicroVM before accepting a turn.

Acceptance criteria:

- Duplicate action submissions apply at most once.
- The browser's die result matches the persisted MicroVM result.
- A resumed session preserves character, world, inventory, facts, and revision.
- Victory and defeat remain authoritative and unmistakable.

Parallelization: Wave 3 packages W3-A and W3-E split turn execution from rehydration testing.

## Slice 10: Synchronized narration and audio

Deliverables:

- Define audio state per ordered opening or narration block.
- Generate or request speech from exactly the text displayed by the client.
- Support play, pause, replay, skip, and disable without mutating game state.
- Cache audio by normalized content hash, language, voice, and engine.
- Record synthesis latency without storing narration in telemetry.

Acceptance criteria:

- Spoken and visible text are identical and ordered identically.
- Reconnecting does not automatically replay old audio.
- Audio failure never blocks gameplay.

Parallelization: Wave 3 package W3-B using static opening fixtures.

## Slice 11: Bedrock narration streaming lab

Deliverables:

- Establish non-streaming time-to-result and quality baselines.
- Implement a separate Narrator experiment using `ConverseStream` only after MicroVM resolution.
- Publish bounded `narration.delta` events and a final checksum or complete narration event.
- Handle client backpressure, disconnects, retries, and incomplete streams.
- Compare direct selected narration with the extra streaming Narrator call.

Acceptance criteria:

- No unvalidated outcome is streamed as fact.
- Reassembled deltas equal the persisted final narration.
- Eval reports quality, total latency, time to first byte, tokens, and cost by approach.
- The default changes only if measured UX improvement justifies the added call.

Parallelization: Wave 3 package W3-C using recorded authoritative outcomes.

## Slice 12: Production-readiness baseline

Deliverables:

- Add CloudWatch dashboard, alarms, tracing, quotas, budgets, and per-user creation limits.
- Add DLQs or failure destinations where asynchronous delivery can fail.
- Add load tests for session creation, WebSocket fan-out, reconnect, and concurrent actions.
- Add threat model and data-retention policy.
- Document runbooks for failed workflows, leaked MicroVMs, Bedrock throttling, and stale connections.

Acceptance criteria:

- Alarms cover workflow failure, MicroVM leakage, Bedrock throttling, and delivery error rates.
- Load tests establish the serverless scaling and cost envelope.
- The ECS revisit triggers in RFC 0001 are evaluated with measurements.
- Public access is not enabled before security and budget controls pass review.

Parallelization: Wave 3 starts telemetry and operations; Wave 4 splits security, load, cost,
alarms, and runbooks into independent packages.

## Deferred experiments

- Step Functions Express for turn orchestration.
- ECS Fargate real-time gateway for direct WebSockets and backpressure control.
- Multiplayer parties and shared session ownership.
- Bidirectional voice input.
- Parallel or speculative world and character generation.
- Longer campaigns and memory summarization.

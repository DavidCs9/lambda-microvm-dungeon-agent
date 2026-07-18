# RFC 0001: Serverless Web Control Plane and Session Orchestration

- Status: Accepted
- Date: 2026-07-18
- Owner: DavidCs9
- Scope: Web client control plane, session creation, real-time events, and durable sessions

## Summary

Move game orchestration out of the local CLI and introduce a web-facing, serverless control plane.
Creating a session will be a Step Functions Standard workflow. The Adventure Architect and
Character Architect will run as independently observable Lambda steps. API Gateway HTTP and
WebSocket APIs will expose the control plane and real-time event channel. DynamoDB will hold
durable session and connection metadata. A dedicated Lambda MicroVM remains authoritative for
active game rules and state.

The Textual TUI is frozen as a reference client. New product UX work targets the web client.

## Context

The original application colocates presentation, AWS client construction, Bedrock agents,
MicroVM lifecycle, and the player loop in a local process. That architecture was useful for
validating Lambda MicroVMs and iterating on gameplay, but it creates four limitations:

1. Players need local AWS credentials and a compatible terminal environment.
2. Sessions cannot be resumed reliably after the temporary MicroVM ends.
3. Initial generation appears frozen while several slow operations execute sequentially.
4. Bedrock streaming and browser clients require a network-accessible orchestration service.

The first real playtest with separate world and character generation used 11 model calls, 53,225
tokens, and 175.87 seconds of aggregate model latency across setup and seven turns. The player
received no phase-level progress during setup. Visual and spoken introductions also diverged
because the TUI rendered the complete `OpeningView` but sent only `opening.scene` to Polly.

## Goals

- Start session creation asynchronously and return a session ID immediately.
- Make every setup phase visible and independently measurable.
- Preserve sessions beyond a single MicroVM lifetime.
- Support reconnectable real-time browser updates.
- Experiment safely with Bedrock `ConverseStream`.
- Preserve the MicroVM as the authority for dice, state transitions, and terminal outcomes.
- Keep presentation, orchestration, model adapters, and game rules independently replaceable.
- Allow different models and inference settings for each agent role.

## Non-goals

- Building the complete web interface in this RFC.
- Moving authoritative game rules out of the MicroVM.
- Running arbitrary model-generated code.
- Supporting multiplayer sessions in the first version.
- Migrating the control plane to ECS before serverless limits are measured.
- Running every player turn as a Step Functions Standard execution.

## Decision

### High-level topology

```text
Browser
  |-- HTTPS --> API Gateway HTTP API --> Control Plane Lambdas
  |-- WebSocket --> API Gateway WebSocket API --> Connection Lambdas
                                                       |
                                                   DynamoDB
                                          sessions / events / connections
                                                       |
                                            Step Functions Standard
                                          create-session state machine
                                             |                 |
                                  Bedrock agent Lambdas   MicroVM manager
                                             |                 |
                                             +--------+--------+
                                                      |
                                              Lambda MicroVM
                                         rules + d20 + active state
```

### Control plane compute

The initial control plane will use Lambda rather than an always-on ECS service.

HTTP requests must perform short control operations only: authenticate, validate, persist intent,
start a workflow, and return. Slow Bedrock and MicroVM work happens asynchronously. The create
endpoint returns `202 Accepted` rather than waiting behind an API Gateway integration timeout.

The existing FastAPI code remains the MicroVM rules API. Control-plane routes will use shared
Pydantic application contracts without requiring a long-lived FastAPI process. A thin FastAPI
adapter may be added later if OpenAPI ergonomics justify it, but domain behavior must not depend on
the adapter.

### Session creation workflow

Use Step Functions Standard because it provides durable execution, exactly-once workflow
semantics, execution history, step-level retries, and room for workflows longer than five minutes.

The initial state machine is:

```text
ValidateSession
  -> CreateSessionRecord
  -> EmitStartingMicrovm
  -> LaunchMicrovm
  -> WaitForMicrovm
  -> EmitCreatingAdventure
  -> GenerateAdventure
  -> PersistAdventure
  -> EmitCreatingCharacter
  -> GenerateCharacter
  -> PersistCharacter
  -> EmitInitializingGame
  -> InitializeMicrovmGame
  -> MarkSessionReady
  -> EmitSessionReady
```

Every Task will define an explicit timeout and bounded retries with exponential backoff and full
jitter. Validation and authorization errors will not be retried. Terminal workflow failures will
mark the session failed and emit a recoverable error event.

The Step Functions payload carries identifiers and small summaries, not full transcripts. Large
or growing artifacts are stored outside the execution to remain below the 256 KiB state limit.

### Agent boundaries

Each model role is an independently deployable adapter behind a typed application port:

- Adventure Architect: creates and validates `AdventurePlan`.
- Character Architect: receives the adventure and creates `PlayerCharacter`.
- Dungeon Master: proposes typed success and failure branches for a turn.
- Narrator, if introduced: streams prose only after the authoritative outcome is known.

World and character generation are separate workflow tasks. Their latency, token usage, repair
attempts, model ID, and errors are recorded separately. Model choice is configuration per role.

### Turn execution

Turns will initially use a dedicated Lambda application flow, not the session-creation state
machine:

```text
player.action
  -> validate ownership and session revision
  -> Dungeon Master structured proposal
  -> MicroVM validates, rolls, and applies one branch
  -> persist authoritative snapshot and event
  -> stream or publish the selected narration
```

A later experiment may compare this with Step Functions Express. Standard workflows are not the
default for individual interactive turns because extra transitions may add latency without
improving the first implementation.

### Real-time transport

API Gateway WebSocket API manages browser connections. Connection records are stored in DynamoDB
with TTL because disconnect delivery is best-effort and API Gateway connections are temporary.

WebSocket delivery is an optimization, not the source of truth. Every significant event receives
a session-local sequence number and is stored before best-effort delivery. A reconnecting client
can request events after its last acknowledged sequence.

Initial event types:

```text
session.creation.started
session.phase.changed
session.creation.failed
session.ready
turn.started
dice.rolled
narration.delta
turn.completed
session.completed
```

Events use a versioned envelope:

```json
{
  "version": 1,
  "eventId": "evt_01...",
  "sessionId": "ses_01...",
  "sequence": 7,
  "type": "session.phase.changed",
  "occurredAt": "2026-07-18T21:00:00Z",
  "payload": {
    "phase": "creating_character",
    "elapsedMs": 38420
  }
}
```

### Bedrock streaming

Structured adjudication cannot be presented as final narration before the MicroVM chooses and
validates a branch. The safe order is:

1. Generate a typed turn proposal.
2. Let the MicroVM validate and roll.
3. Select the authoritative outcome.
4. Stream only narration consistent with that outcome.

The first implementation may publish the already-generated selected narration as one event. A
subsequent lab will evaluate a separate Narrator using `ConverseStream`. This adds a model call and
must be evaluated for latency, cost, and narrative quality before becoming the default.

### Durable storage

DynamoDB is the initial system of record for:

- session ownership, lifecycle status, language, revision, and active MicroVM reference;
- connection IDs and expiration;
- ordered session events;
- compact authoritative state snapshots or references to them;
- idempotency records for session creation and player actions.

S3 is reserved for larger immutable artifacts such as complete plans, transcripts, exports, or
evaluation captures if DynamoDB item size becomes restrictive.

A durable `sessionId` identifies the game. A `microvmId` identifies only the current compute
incarnation. Resuming a session may launch a new MicroVM and rehydrate its last validated snapshot.

### Introduction and audio synchronization

The opening is represented as one ordered collection of presentation-neutral content blocks. The
web client renders and narrates the same blocks in the same order. Polly must not receive an
independently assembled subset.

The initial sequence is character identity, background, motivation, prior knowledge, immediate
situation, and possible first actions. Audio state is tracked per block so the client can pause,
skip, replay, or disable speech without changing game state.

### Observability

Every request and event carries `sessionId`, `correlationId`, and, when applicable,
`workflowExecutionArn` and `turnId`. Logs must not contain prompts, narration, auth tokens, or
private player input by default.

Required measurements include:

- API request latency and error rate;
- workflow duration and per-state duration;
- MicroVM launch and readiness time;
- agent model ID, calls, input/output tokens, model latency, repairs, and failures;
- time to first progress event;
- time to session ready;
- WebSocket delivery failures and reconnects;
- turn time to dice result and time to first narration byte.

CloudWatch dashboards and alarms are added after the first vertical slice establishes metric names.

### Security

- HTTP and WebSocket connections require authenticated user identity.
- Every session operation verifies ownership server-side.
- Lambda roles are scoped by responsibility; model Lambdas do not manage MicroVMs.
- MicroVMs never receive Bedrock, Polly, or control-plane credentials.
- Auth tokens and WebSocket connection IDs are not written to normal application logs.
- All state mutations use revision checks or idempotency keys.
- DynamoDB, S3, logs, and event payloads use encryption at rest.
- Rate limits and per-user session quotas are enforced before starting paid work.

## Alternatives considered

### FastAPI on ECS Fargate

Fargate provides native long-lived WebSockets and direct streaming from one process. It also adds
an always-on service, ALB, deployment draining, connection-aware scaling, container operations,
and a larger security surface. It is deferred until API Gateway and Lambda limitations are
measured. A future architecture may move only the real-time gateway to ECS while retaining the
serverless control plane and Step Functions workflow.

### FastAPI monolith on Lambda

This would ease migration but risk hiding long operations behind synchronous HTTP handlers. A thin
adapter remains possible, but application use cases and agent steps will be explicit functions
rather than a single orchestration script or lambdalith.

### Step Functions Express for session creation

Express has a five-minute maximum and weaker durability semantics for this use case. Standard is
preferred for diagnosability, idempotent execution naming, and future callback or wait states.

### One Step Functions execution per turn

This remains a useful experiment, especially with Express, but is deferred until the direct Lambda
turn path establishes latency and cost baselines.

### WebSocket state held only in memory

This prevents reliable reconnects and ties sessions to a particular process. Durable events and
connection metadata are required from the beginning.

## Consequences

### Positive

- Browser clients no longer require AWS credentials.
- Setup phases become visible, recoverable, and measurable.
- Sessions survive browser disconnects and MicroVM replacement.
- Agent models can evolve independently.
- The architecture creates focused labs for Step Functions, WebSockets, and Bedrock streaming.

### Costs

- More deployed resources and IAM roles.
- Eventual consistency between workflow, event delivery, and the browser.
- Explicit idempotency, event sequencing, and rehydration logic.
- WebSocket reconnect behavior must be designed and tested.
- A second backend surface exists alongside the internal MicroVM FastAPI API.

## Validation criteria

The architecture is validated when one browser can:

1. create an authenticated session and receive `202` within two seconds;
2. observe truthful setup phases over WebSocket;
3. disconnect and recover missed events in sequence;
4. receive a world and character generated by separate workflow steps;
5. read and hear the same ordered opening content;
6. submit one free-form action;
7. see an authoritative die roll and resulting narration;
8. close the browser and later rehydrate the session into a new MicroVM;
9. inspect phase-level latency and model usage without exposing gameplay content in logs.

## Revisit triggers

Re-evaluate ECS Fargate or a dedicated streaming gateway if measurements show any of the following:

- API Gateway connection limits materially harm the intended session length;
- `post_to_connection` overhead prevents acceptable narration streaming;
- Lambda duration or concurrency becomes a binding constraint;
- backpressure or continuous bidirectional audio requires process-owned connections;
- serverless cost exceeds an equivalent continuously utilized Fargate service.


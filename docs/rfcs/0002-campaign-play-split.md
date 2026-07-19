# RFC 0002: Campaign and Play Control Plane Split

- Status: Proposed
- Date: 2026-07-18
- Owner: DavidCs9
- Scope: Reusable campaigns, split of session creation into campaign creation and session play

## Summary

Split the session-creation flow from [RFC 0001](0001-web-control-plane.md) into two control plane
surfaces. A campaign control plane owns the expensive, one-time generation of a world and its
protagonist and stores the result as a reusable campaign. A play control plane starts sessions
against an existing ready campaign without any model calls. Each play session forks an independent
copy of the campaign state, so one campaign supports many replays.

This is one deployed control plane with two route families and two Step Functions state machines,
not two separate services.

## Context

RFC 0001 creates every session from scratch: the create-session state machine generates and
persists an adventure, then generates and persists a character, then initializes the MicroVM. The
first measured playtest used 11 model calls, 53,225 tokens, and 175.87 seconds of aggregate model
latency, and most of that cost is world and character generation. Because the generated world is
bound to the session that created it, a player who wants to replay the same world, or simply start
a second run after a failure, pays the full generation cost and latency again and receives a
different world anyway.

The generation steps are also the main source of session-creation latency and failure modes
(model retries, repair attempts, token variability). They have no need to run on the interactive
path: their output is immutable once validated.

## Goals

- Pay world and character generation cost once per campaign, not once per session.
- Start a play session with zero model calls: validation, MicroVM launch, and rehydration only.
- Keep campaign creation asynchronous, observable, and phased like session creation is today.
- Allow many independent sessions from one campaign (fork semantics, no cross-session coupling).
- Keep the MicroVM authoritative for dice, state transitions, and outcomes during play.
- Preserve the per-role model configuration and per-step observability from RFC 0001.

## Non-goals

- Sharing campaigns between players or a public campaign gallery.
- Editing a campaign after it becomes ready. Regeneration means creating a new campaign.
- Persistent campaign worlds that evolve across sessions.
- Multiplayer sessions.
- Two separately deployed control plane services.
- Migrating the local CLI flow; it may keep generating one-shot sessions as it does today.

## Decision

### What a campaign is

A campaign is an immutable, owner-scoped, reusable game template:

- one validated `AdventurePlan` (world, stakes, opening situation);
- one validated `PlayerCharacter` generated against that plan, as today;
- locale, schema versions, creation metrics (model IDs, tokens, latency, repairs), and a
  monotonically increasing `revision`.

A campaign is created once, reaches `ready`, and does not change afterwards. In-flight and future
sessions always see a stable snapshot.

### Control plane topology

One control plane deployment, two route families and two state machines:

```text
Browser
  |-- HTTPS --> API Gateway HTTP API
  |               |-- /campaigns/* --> Campaign Lambdas --> create-campaign state machine
  |               |-- /sessions/*  --> Play Lambdas     --> create-session state machine
  |-- WebSocket --> API Gateway WebSocket API --> Connection Lambdas
                                                        |
                                                    DynamoDB
                                       campaigns / sessions / events / connections
                                                        |
                                            Lambda MicroVM (per active session)
```

Campaign APIs and session APIs share authentication, ownership checks, the event channel,
idempotency handling, and storage conventions from RFC 0001.

### Campaign creation workflow

The create-campaign state machine is the generation half of today's create-session machine, with
no MicroVM involvement:

```text
ValidateCampaign
  -> CreateCampaignRecord
  -> EmitCreatingAdventure
  -> GenerateAdventure
  -> PersistAdventure
  -> EmitCreatingCharacter
  -> GenerateCharacter
  -> PersistCharacter
  -> MarkCampaignReady
  -> EmitCampaignReady
```

Campaign creation launches no MicroVM. The world and character are validated and persisted in
control plane storage; compute is only needed when someone plays.

`POST /campaigns` returns `202 Accepted` with a `campaignId` immediately, enforces per-user
campaign quotas and rate limits before starting paid generation, and accepts an idempotency key.
Failures mark the campaign `failed` with a recoverable error event, mirroring session creation.

### Session creation against a campaign

`POST /sessions` now takes a `campaignId`. The revised create-session state machine:

```text
ValidateSession
  -> CreateSessionRecord
  -> EmitStartingMicrovm
  -> LaunchMicrovm
  -> WaitForMicrovm
  -> EmitInitializingGame
  -> ForkCampaignIntoSession
  -> InitializeMicrovmGame
  -> MarkSessionReady
  -> EmitSessionReady
```

`ValidateSession` checks ownership of the campaign, that the campaign is `ready`, and per-user
session quotas. `ForkCampaignIntoSession` copies the campaign's adventure and character at the
recorded `campaignRevision` into the session's own state; from that point the session evolves
independently and the campaign is never read again during play. The session record stores
`campaignId` and `campaignRevision` for traceability.

The expected session-creation latency drops from minutes to MicroVM launch plus snapshot load,
and the only paid resources on the play path are the MicroVM and turn-time Dungeon Master calls.

### Fork semantics

Sessions are forks, not views. Consequences in one session never write back to the campaign and
are never visible to other sessions of the same campaign. Replays start from the identical
opening state. This keeps all cross-session merge, locking, and continuity problems out of v1.

### Storage

DynamoDB gains a campaigns table: `campaignId`, owner, lifecycle status, locale, `revision`,
adventure and character payloads (or S3 references when item size requires), generation metrics,
idempotency records, and timestamps. The sessions table gains `campaignId` and
`campaignRevision`.

Because campaigns now outlive deployments, persisted campaign payloads carry an explicit schema
version, and the play path must accept all still-supported versions or reject them with a clear
error.

### Events

New event types reuse the versioned envelope and per-aggregate sequencing from RFC 0001:

```text
campaign.creation.started
campaign.phase.changed
campaign.creation.failed
campaign.ready
```

Session events are unchanged, but session setup no longer emits adventure- or
character-generation phases; the phases are MicroVM startup and game initialization.

### Observability

Campaign-level metrics are recorded once per campaign: per-role model IDs, calls, tokens,
latency, and repairs. Session-creation metrics now isolate MicroVM launch, wait, fork, and
initialization durations, which makes the pre/post-split latency comparison direct. Session
records joinable by `campaignId` support replays-per-campaign and cost-per-campaign accounting.

### Security

- Campaigns are owner-only; every campaign and session operation verifies ownership server-side.
- Campaign creation quotas and rate limits are enforced before starting paid generation work.
- Sessions-per-campaign and concurrent-session quotas prevent quota laundering through one
  expensive campaign.
- Lambda roles stay scoped by responsibility: generation Lambdas do not manage MicroVMs.
- MicroVMs still receive no Bedrock, Polly, or control-plane credentials.

## Alternatives considered

### Keep one flow, cache generated worlds internally

Generating on session start and silently reusing worlds would hide what the player is paying for
and when. An explicit campaign entity makes the cost boundary, lifecycle, and ownership visible
and gives replays a stable identity.

### Campaign contains the world only, character generated per session

This preserves per-session character novelty but keeps a model call, its latency, and its failure
modes on the session-start path. The character is already generated against the plan, so
pre-generating it loses little; a character roster or per-session regeneration can be added later
without changing the campaign entity.

### Persistent campaign world shared across sessions

Continuity across plays is attractive but requires write-back, merge, and locking semantics, and
makes replays non-identical. Fork semantics delivers the reuse benefit without that complexity; a
persistent-world variant can build on the campaign entity later.

### Two separately deployed control planes

Two services would double API Gateway, IAM, deployment, and observability surface for no runtime
benefit, since both surfaces share auth, storage, and the event channel. The split is at the
route-family and state-machine level; a future scale or team-boundary need can still peel the
campaign surface off.

## Consequences

### Positive

- Session creation becomes fast and model-free; generation cost is paid once per campaign.
- Generation failures no longer block a player who just wants to play a ready campaign.
- Replays of a world are possible and start from identical state.
- Campaign creation needs no MicroVM, so idle compute is never launched for unplayed campaigns.
- Cost attribution improves: generation per campaign, play per session.

### Costs

- A new DynamoDB table, route family, state machine, and event types.
- Persisted campaign payloads need schema versioning across deployments.
- Players must create a campaign before their first session; onboarding gains a step.
- Immutable campaigns mean fixes to a broken world require creating a new campaign.
- The RFC 0001 create-session workflow is superseded in part; local CLI and web flows diverge
  until the CLI is updated or retired.

## Relationship to RFC 0001

RFC 0001 remains accepted. This RFC moves the `GenerateAdventure`, `PersistAdventure`,
`GenerateCharacter`, and `PersistCharacter` states out of the create-session state machine into a
new create-campaign state machine, adds the campaigns table and events, and changes
`POST /sessions` to require a `campaignId`. Everything else in RFC 0001 (turn execution,
WebSocket transport, durability, streaming, security) is unchanged.

## Validation criteria

The split is validated when one browser can:

1. create a campaign and receive `202` within two seconds;
2. observe truthful campaign creation phases over WebSocket;
3. see the campaign reach `ready` with a world and protagonist from separate workflow steps;
4. start two sessions against the same campaign with zero model calls on the session path;
5. observe both sessions fork identical opening state and then diverge independently;
6. verify the campaign is unchanged after both sessions complete;
7. confirm campaign ownership is enforced for another user's `campaignId`;
8. read generation cost per campaign and play cost per session from metrics.

## Revisit triggers

- Players need character novelty per session: add a pre-generated roster or optional per-session
  character regeneration.
- Players need campaign continuity: design write-back and revision semantics on top of the
  campaign entity.
- Campaigns need to be shared or published: introduce sharing and authorization as a separate
  RFC.
- The campaign surface diverges operationally: consider a separate deployment then, not now.

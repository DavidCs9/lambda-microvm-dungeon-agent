# Campaign and Play Split Implementation Plan

This plan implements [RFC 0002](../rfcs/0002-campaign-play-split.md) on top of the RFC 0001
control plane. Backend only; the web client is out of scope. Each slice keeps the existing
contract discipline: versioned schemas, framework-neutral domain code, conditional writes, and
durable events before best-effort delivery.

## Decision summary

- A campaign is an immutable, owner-scoped template: one validated `AdventurePlan`, one validated
  `PlayerCharacter`, an ordered opening document, locale, schema versions, generation metrics, and
  a monotonically increasing `revision`.
- One deployed control plane, two route families (`/campaigns/*`, `/sessions/*`) and two Standard
  state machines (`create-campaign`, `create-session`).
- `POST /sessions` requires a `campaignId`; session creation performs zero model calls.
- Sessions fork campaign state at `campaignRevision`; campaigns are never read during play.

## Slices

### Slice 1: Campaign contracts (merge barrier)

- `CampaignId` (`cam_` + Crockford UUIDv7) and `new_campaign_id()`.
- `CampaignStatus` (requested, creating, ready, failed) and `CampaignPhase` (requested,
  creating_adventure, creating_character, ready, failed) with transition maps.
- New event types `campaign.creation.started`, `campaign.phase.changed`,
  `campaign.creation.failed`, `campaign.ready` with typed payloads and a `CampaignEvent` envelope
  (per-campaign sequencing).
- `CampaignRecord` with lifecycle validation mirroring `SessionRecord`, plus
  `RoleGenerationMetrics` / `CampaignGenerationMetrics` (model ID, calls, tokens, latency,
  repairs).
- `SessionRecord` gains optional `campaignId` / `campaignRevision`; `CreateSessionCommand` and
  `CreateSessionWorkflowInput` require them.
- `SessionPhase` drops `creating_adventure` / `creating_character`; session setup transitions from
  `waiting_for_microvm` straight to `initializing_game`.
- New error codes: `campaign_not_found`, `campaign_conflict`, `campaign_creation_failed`,
  `quota_exceeded`.
- New ports: `CampaignRepository`, `CampaignEventRepository`, `CampaignFactoryPort`,
  `CampaignEventDeliveryPort`; `WorkflowStarterPort.start_create_campaign`; session repository
  quota counts.

### Slice 2: Persistence

- In-memory campaign repository (records, idempotency, ordered events, owner counts).
- DynamoDB campaign repository on a new campaigns table (same single-table conventions:
  `CAMPAIGN#{id}` metadata, `EVENT#{seq}` events, owner-scoped idempotency with TTL).
- Session table gains GSIs `ByOwner` (ownerId) and `ByCampaign` (campaignId); campaigns table gains
  `ByOwner`. Session items carry top-level `status` and `campaignId` for quota COUNT queries.

### Slice 3: Campaign creation workflow

- Adventure and character steps move to campaign scope (`CreateCampaignWorkflowInput`, campaign
  artifact refs) without changing their generation logic.
- Campaign artifact stores keyed `CAMPAIGN#{id}` hold adventure, character, and opening.
- `DurableCampaignWorkflowStub` implements ValidateCampaign -> CreateCampaignRecord ->
  EmitCreatingAdventure -> GenerateAdventure -> PersistAdventure -> EmitCreatingCharacter ->
  GenerateCharacter -> PersistCharacter -> MarkCampaignReady -> EmitCampaignReady, plus the
  MarkCampaignFailed -> EmitCampaignCreationFailed terminal path.
- Per-role `RoleMetricsCollector` aggregates calls, tokens, latency, and repairs onto the campaign
  record at MarkCampaignReady; reset at CreateCampaignRecord so warm Lambda instances never leak
  metrics across campaigns.

### Slice 4: Session creation against a campaign

- `POST /sessions` takes `campaignId`; the handler enforces ownership, ready status, and quotas
  (active sessions per owner, sessions per campaign) before starting paid work.
- Revised create-session machine: ValidateSession -> CreateSessionRecord -> EmitStartingMicrovm ->
  LaunchMicrovm -> WaitForMicrovm -> EmitInitializingGame -> ForkCampaignIntoSession ->
  InitializeMicrovmGame -> MarkSessionReady -> EmitSessionReady.
- ForkCampaignIntoSession re-checks the campaign is ready, copies adventure, character, and
  opening into session-scoped artifacts, and never reads the campaign again.

### Slice 5: HTTP and realtime surfaces

- `POST /campaigns` (202 + campaignId, idempotency key, per-user campaign quota),
  `GET /campaigns/{campaignId}`, `GET /campaigns/{campaignId}/events`.
- WebSocket `subscribe` accepts `campaignId` or `sessionId`; campaign events fan out to campaign
  subscribers with the same store-then-deliver discipline.

### Slice 6: Infrastructure

- Campaigns table, campaign state machine with log group, role, alarms, and terminal-event rule
  coverage; new routes; GSIs; IAM scoped so generation Lambdas do not manage MicroVMs.

## Validation (backend subset of RFC 0002 criteria)

- Campaign creation returns 202 and reaches ready through observable phases.
- Two sessions against one campaign fork identical opening state and diverge independently; the
  campaign is unchanged.
- Cross-user campaign and session access is rejected.
- Quotas reject over-limit creation before paid work starts.
- Generation metrics are readable per campaign; session creation performs no model calls.

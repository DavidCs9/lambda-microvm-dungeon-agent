# RFC 0002 — Implementation Progress Analysis

Branch: `feat/rfc0002-analysis` (analysis only, no code changes)
Date: 2026-07-19

## Overall: ~80% complete

The heavy lifting (domain models, persistence, workflow logic, HTTP handlers, tests) is done.
What's missing is the Infrastructure-as-Code for the campaign state machine and a few integration
touch points.

---

## Slice 1: Campaign Contracts ✅ DONE

| Item | Status | File |
|------|--------|------|
| `CampaignId` (`cam_` + Crockford UUIDv7) | ✅ | `identifiers.py:31` |
| `CampaignStatus` / `CampaignPhase` with transitions | ✅ | `domain/enums.py`, `domain/lifecycle.py` |
| Campaign event types (`campaign.creation.started`, etc.) | ✅ | `domain/enums.py` (EventType) |
| Campaign event payloads | ✅ | `domain/models.py` (4 payload classes) |
| `CampaignRecord` with lifecycle validation | ✅ | `domain/models.py` |
| `CampaignGenerationMetrics` | ✅ | `domain/models.py` |
| `SessionRecord` gains `campaignId` / `campaignRevision` | ✅ | `domain/models.py` |
| `SessionPhase` drops `creating_adventure` / `creating_character` | ✅ | `domain/enums.py` (SessionPhase) |
| New error codes | ✅ | `domain/enums.py` (ErrorCode) |
| New ports (`CampaignRepository`, etc.) | ✅ | `domain/ports.py` |
| `CreateCampaignCommand` / `CreateSessionWorkflowInput` | ✅ | `domain/models.py` |

**What's missing:** nothing.

---

## Slice 2: Persistence ✅ DONE

| Item | Status | File |
|------|--------|------|
| In-memory campaign repository | ✅ | `persistence/memory.py` |
| DynamoDB campaign repository | ✅ | `persistence/dynamodb_campaigns.py` (370 lines) |
| Session table GSIs (ByOwner, ByCampaign) | ✅ | infra template |
| `count_by_campaign` for quota | ✅ | `persistence/memory.py`, `persistence/dynamodb.py` |

**What's missing:** nothing.

---

## Slice 3: Campaign Creation Workflow ✅ DONE

| Item | Status | File |
|------|--------|------|
| `DurableCampaignWorkflowStub` | ✅ | `workflow/campaigns.py` (317 lines) |
| Adventure/character steps refactored for campaign scope | ✅ | `steps/adventure.py`, `steps/character.py` |
| All campaign operations (Validate→Create→Generate→Persist→MarkReady) | ✅ | `workflow/campaigns.py` |
| Campaign failure path | ✅ | `workflow/campaigns.py` |
| `RoleMetricsCollector` for campaign metrics | ✅ | `agents/metrics.py` |
| `CampaignAdventureLoader` / `CampaignCharacterLoader` | ✅ | `workflow/stub.py` |

**What's missing:** nothing.

---

## Slice 4: Session Creation Against Campaign ✅ DONE

| Item | Status | File |
|------|--------|------|
| `POST /sessions` takes `campaignId` | ✅ | `http/handlers.py:105` |
| Ownership, ready status, quota checks | ✅ | `http/handlers.py:105-116` |
| Revised state machine (no generation steps) | ✅ | `workflow/stub.py` |
| `ForkCampaignIntoSession` operation | ✅ | `workflow/stub.py:168-272` |
| Zero model calls on session path | ✅ | architecture |

**What's missing:** nothing.

---

## Slice 5: HTTP and Realtime Surfaces ✅ DONE (code)

| Item | Status | File |
|------|--------|------|
| `POST /campaigns` (202 + campaignId) | ✅ | `http/handlers.py` |
| `GET /campaigns/{campaignId}` | ✅ | `http/handlers.py` |
| `GET /campaigns/{campaignId}/events` | ✅ | `http/handlers.py` |
| Campaign routes in API Gateway | ✅ | `http/api_gateway.py` (18 refs) |
| WebSocket `subscribe` for campaign events | ✅ | `realtime/service.py` |
| Campaign event store-then-deliver | ✅ | `realtime/service.py` |

**What's missing:** nothing in code — the HTTP handlers and WebSocket support are there.

---

## Slice 6: Infrastructure 🟡 PARTIALLY DONE

| Item | Status | File |
|------|--------|------|
| `CampaignTable` DynamoDB | ✅ | infra template (line 60) |
| Campaign routes in API Gateway | ✅ | infra template (lines 166-184) |
| Campaign table referenced in function policies | ✅ | infra template (line 219) |
| **`CreateCampaignStateMachine`** | **❌ MISSING** | infra template — `!GetAtt` at lines 118, 129 but resource **never defined** |
| Campaign state machine log group | **❌ MISSING** | only `CreateSessionWorkflowLogGroup` exists |
| Campaign state machine IAM role | **❌ MISSING** | only `CreateSessionStateMachineRole` exists |
| Campaign state machine alarms | **❌ MISSING** | alarms only reference create-session state machine |
| Campaign terminal event rule | **❌ MISSING** | `WorkflowTerminalStatusRule` only covers session machine |
| Campaign table in Outputs | **❌ MISSING** | output only has SessionTable, not CampaignTable |

---

## Tests ✅ DONE

| Test | Status | Lines |
|------|--------|-------|
| Campaign domain + repository tests | ✅ | 222 |
| Campaign workflow E2E test | ✅ | 267 |
| Persistence tests (includes campaign) | ✅ | 310 |

---

## Summary

| Slice | Status | Est. effort to finish |
|-------|--------|----------------------|
| 1 — Contracts | ✅ Done | — |
| 2 — Persistence | ✅ Done | — |
| 3 — Campaign Workflow | ✅ Done | — |
| 4 — Session Creation | ✅ Done | — |
| 5 — HTTP/Realtime | ✅ Done | — |
| **6 — Infrastructure** | **🟡 Partial** | **~2-3h** |
| **Tests** | **✅ Done** | — |

### What's left (Infrastructure only)

1. **Define `CreateCampaignStateMachine`** — Standard state machine with the campaign workflow
   steps from `campaigns.py` (ValidateCampaign → CreateCampaignRecord → GenerateAdventure →
   GenerateCharacter → MarkCampaignReady). Follow the same pattern as `CreateSessionStateMachine`.

2. **Create campaign state machine IAM role** — `CreateCampaignStateMachineRole` with invoke
   permission on `WorkflowTaskFunction`, read/write on `CampaignTable`, and CloudWatch logging.

3. **Campaign workflow log group** — `CreateCampaignWorkflowLogGroup` for state machine logs.

4. **Campaign state machine alarms** — `CampaignWorkflowFailedAlarm`, `CampaignWorkflowTimedOutAlarm`,
   `CampaignWorkflowAbortedAlarm`, following the session pattern.

5. **Campaign terminal event rule** — `CampaignWorkflowTerminalStatusRule` monitoring campaign
   state machine executions (or extend existing rule to cover both state machine ARNs).

6. **CampaignTable name in Outputs** — Add `CampaignTableName` to outputs section.

### Total remaining effort: ~2-3 hours
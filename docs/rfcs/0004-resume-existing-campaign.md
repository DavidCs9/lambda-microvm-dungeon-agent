# RFC 0004: Resume Existing Campaign (Backend and Client)

- Status: Proposed
- Date: 2026-07-19
- Owner: DavidCs9
- Scope: Owner-scoped campaign list and resume path for sandbox demos

## Summary

Friends and the lab operator already pay for campaign generation once (RFC 0002), but the
showcase client from [RFC 0003](0003-videogame-web-client.md) can only forge a new campaign.
After a refresh or a lost tab, the only path is another `POST /campaigns`. This RFC adds a
minimal resume surface on both sides: the control plane exposes the owner's campaigns and the
opening for a ready campaign; the browser lets the player pick an existing ready campaign and
continue into the opening scroll and play session without regenerating the world.

Lab posture stays: ship the happy path friends need, reuse the existing `ByOwner` index and
ownership checks, no gallery product, no Cognito.

## Context

RFC 0002 made campaigns reusable templates. Session start is MicroVM launch plus fork with zero
model calls. That only helps if the client can find a ready campaign again.

Today:

- Backend: `POST /campaigns`, `GET /campaigns/{campaignId}`, `GET /campaigns/{campaignId}/events`.
  The campaign table already has a `ByOwner` GSI (`ProjectionType: ALL`) used only for quota
  `COUNT`. There is no list route.
- `CampaignRecord` does not embed the `OpeningDocument`. Opening arrives on
  `campaign.ready` (and again on `session.ready`). Resume after a cold load cannot rebuild the
  opening scroll from `GET /campaigns/{id}` alone.
- Frontend: ritual screen only offers **Forjar campaña**. No list, no paste-id resume, no
  persistence of recent campaign ids beyond what happens to sit in memory.

During RFC 0003 browser playtests this gap blocked e2e recovery: a closed Chrome tab meant
forging another campaign or abandoning the demo.

## Goals

- List campaigns owned by the authenticated sandbox player (`x-player-id` / `playerId`).
- Resume a `ready` campaign into the existing opening scroll, then `POST /sessions` as today.
- Expose the opening for a ready campaign over HTTP so the client does not depend on replaying
  the full WebSocket history just to show the scroll.
- Keep ownership enforcement identical to `GET /campaigns/{campaignId}`.
- Extend the RFC 0003 ritual UX with "use an existing campaign" without turning it into a
  dashboard.

## Non-goals

- Sharing campaigns between players or a public gallery (still out of scope per RFC 0002).
- Editing, deleting, or regenerating campaigns after `ready`.
- Listing or resuming in-flight sessions (session resume may be a later RFC).
- Cognito / JWT; sandbox `x-player-id` remains the auth story.
- Perfect pagination products, search, tags, or campaign cover art.
- Changing MicroVM fork semantics or play contracts from RFC 0002.

## Decision

### Backend

#### `GET /campaigns`

New HTTP route on the existing control-plane API:

- Auth: same sandbox identity as today.
- Behavior: query campaign table `ByOwner` for `ownerId = identity.owner_id`.
- Default order: newest `createdAt` / `updatedAt` first (client-sortable if the wire order is
  GSI-natural; document the chosen order in the handler).
- Optional query: `status=ready` (and optionally `creating` / `failed`) to keep the demo list
  short. If omitted, return all statuses so the UI can show in-flight or failed entries lightly.
- Response envelope (camelCase, versioned like other contracts):

```text
CampaignListEnvelope {
  version: 1
  campaigns: CampaignRecord[]
}
```

Reuse `CampaignRecord` on the wire. Do not invent a second schema unless list payloads get too
large; if they do, introduce a thin `CampaignSummary` with id, status, phase, language,
revision, timestamps, and optional title — still owner-scoped.

Soft limit for the lab: return at most a small page (for example 50). No cursor pagination in
v1 unless demos exceed that. Prefer a hard cap over enterprise paging.

Infra: add `GET /campaigns` to the HTTP API (same Lambda as other campaign GETs). IAM already
allows Query on the campaign table for quota; confirm Query on `ByOwner` remains allowed.

Port change: `CampaignRepository.list_by_owner(owner_id, *, status=None) -> tuple[CampaignRecord, ...]`.
Memory adapter for tests mirrors DynamoDB behavior.

#### `GET /campaigns/{campaignId}/opening`

New route for ready campaigns:

- Auth + ownership: same as `GET /campaigns/{campaignId}`.
- `200` + `OpeningEnvelope { version: 1, campaignId, opening: OpeningDocument }` when status is
  `ready` and the opening artifact can be loaded from the campaign's character ref (same loader
  session creation already uses).
- `404` if campaign missing or not owned.
- `409` (or `400` with stable error code) if campaign is not `ready` yet / failed — client should
  not show the opening scroll.

This avoids forcing the SPA to subscribe and replay every campaign event after a cold start just
to obtain the title and blocks.

Alternative considered and rejected for v1: denormalizing the full opening onto `CampaignRecord`.
Title denormalization onto the record at `MarkCampaignReady` is an optional follow-up if list
cards need a human title without a second fetch; not required to accept this RFC if the FE loads
opening only after selection.

#### Unchanged

- `POST /campaigns`, `POST /sessions` with `campaignId`, WebSocket subscribe semantics, and fork
  on session start remain as in RFC 0002.
- No change to event types.

### Frontend (RFC 0003 client)

Extend the ritual / landing spine; do not add an admin console.

```text
Landing
  -> Ritual
       |-- Forjar campaña          (existing create path)
       |-- Mis campañas            (new: GET /campaigns?status=ready)
       `-> select ready campaign
             -> GET opening
             -> Opening scroll     (existing screen)
             -> Comenzar aventura  (existing startSession)
```

UX rules:

- Spanish copy. One job per screen.
- List is sparse: title (from opening or short id fallback), status, maybe language — not a
  data table of JSON.
- Selecting a non-ready campaign: show short status / allow wait only if we also list creating;
  primary path is ready-only.
- After select: set store `campaign`, `opening`, `screen=opening`; subscribe to the campaign
  (optional if already ready) then proceed as today.
- Keep **Forjar campaña** as the primary forge CTA; resume is a peer action on the same ritual
  composition, not a separate product area.
- Optional lab convenience: remember last few `campaignId`s in `localStorage` as a client cache,
  but the source of truth is `GET /campaigns`, not the cache alone.

Net/store:

- `api.listCampaigns(status?)`, `api.getCampaignOpening(campaignId)`.
- `gameActions.loadCampaigns()`, `gameActions.resumeCampaign(campaignId)`.

Debug lab console (`/debug.html`) may gain the same two calls later; not a gate for this RFC.

## Alternatives considered

### Client-only localStorage of campaign ids

Fastest, no deploy. Insufficient alone: another browser, cleared storage, or a friend on a new
device cannot see campaigns that already exist for that `playerId`. Keep as a cache, not the
product contract.

### Replay `GET .../events` to recover opening

Works without a new opening route, but forces the client to page events and special-case
`campaign.ready`. Worse DX and fragile for large histories. Rejected for the happy path.

### Public or shared campaign gallery

Explicit non-goal in RFC 0002. Out of scope here.

## Consequences

### Positive

- Demos can forge once and replay many sessions without burning Bedrock on every browser restart.
- Aligns the client with the economic intent of RFC 0002.
- Uses the existing `ByOwner` index instead of a new table.

### Costs

- One new list route and one opening route to implement, test lightly, and deploy to sandbox.
- List UX must stay sparse so the ritual does not become a dashboard.
- Opening load depends on artifact storage remaining reachable for ready campaigns.

## Relationship to prior RFCs

- [RFC 0001](0001-web-control-plane.md): auth, errors, events, HTTP conventions unchanged.
- [RFC 0002](0002-campaign-play-split.md): campaigns remain immutable ready templates; this RFC
  only discovers and resumes them for the owner.
- [RFC 0003](0003-videogame-web-client.md): presentation spine gains a resume branch; stack and
  atmosphere decisions stand.

## Validation criteria

Accept when, against sandbox with `x-player-id`:

1. `GET /campaigns` returns only that owner's campaigns.
2. A `ready` campaign can be selected in the showcase client and shows the Spanish opening
   without calling `POST /campaigns` again.
3. From that opening, `POST /sessions` reaches the play table and a turn still works.
4. Another `playerId` cannot list or open the first player's campaigns (403/404 as today).
5. Manual friend demo: forge once, refresh the SPA, resume the same campaign, play.

Automated coverage: a few handler/repo unit tests for list ownership and opening-ready checks.
No frontend CI matrix required (same posture as RFC 0003).

## Revisit triggers

- Owners have more campaigns than a single capped page: add cursor pagination.
- List cards need titles without a second request: denormalize `openingTitle` on `CampaignRecord`
  at ready time.
- Friends need to share a campaign id: separate sharing/authorization RFC.
- Session reconnect across refresh becomes as important as campaign resume: session list/resume
  RFC.

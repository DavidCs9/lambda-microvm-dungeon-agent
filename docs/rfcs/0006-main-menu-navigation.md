# RFC 0006: Main-Menu Navigation — Nueva partida, Continuar, Crear campaña

- Status: Proposed
- Date: 2026-07-19
- Owner: DavidCs9
- Scope: Menu-driven navigation in the web client; active-session list and
  session abandon endpoints in the control plane

## Summary

Replace the ceremonial landing → ritual spine with one main menu of three verbs:

- **Nueva partida** → campaign list → pick one → opening → play.
- **Continuar** → straight back into your live session (a pick list when more than one is
  active), rebuilt from the backend — closing the tab no longer kills your game.
- **Crear campaña** → forge flow → opening of the new world → play; the campaign list is
  updated for next time.

This makes "continue" real for the first time. Today the entire session lives in browser
memory: a refresh silently abandons the run, and the orphaned session holds one of the 3
active slots (and its MicroVM) forever — three lost tabs means a permanent `429` with no
recovery. So Continuar has a hard dependency: a session **abandon** endpoint that frees the
slot and stops the cost, exposed per row in the continue list and in the play screen's exit.

Lab posture: three verbs, no dashboard, no router, no new indexes. Everything below runs on
the existing `ByOwner` sessions GSI and the existing `GET /sessions/{id}/events` route.

## Context

Why the spine fails (audit of `web/src/`):

- Landing and ritual are two full screens that do one thing: gate the two real actions. The
  returning player — the common case since RFC 0004 — re-walks both every visit.
- There is no continue path at all. Session state is in-memory only; refresh = lost run. RFC
  0004 deferred "session resume" as maybe-its-own-RFC; the menu model makes it a first-class
  verb, and the plumbing turns out to already exist.
- Nothing can abandon a session. Sessions complete only on won/lost
  (`application/turns.py`); `READY`/`ACTIVE` orphans count against
  `max_active_sessions_per_owner = 3` forever (`count_active_by_owner`) and keep their
  MicroVM running. Any continue feature makes this leak visible, so the fix ships together.

What already exists and is reused:

- Sessions table `ByOwner` GSI — used today by `count_active_by_owner`; the active-session
  list is the same query without the count.
- `GET /sessions/{sessionId}/events` — replaying `turn.completed` payloads rebuilds the
  transcript client-side; no new route for history.
- MicroVM self-healing — `turns.py` rehydrates a dead MicroVM on the next turn, so a
  continued session needs no special revive path.
- RFC 0005 (proposed): titled campaign cards, docked opening CTA, play-table **Salir**, human
  error map, design system. This RFC assumes that layout; its navigation sections are
  superseded by this menu.

## Goals

- One menu, three verbs, no ceremonial screens between the player and the game.
- Continue survives refresh: re-enter a live session with its full transcript.
- Every exit the client offers frees the quota slot and terminates the MicroVM.
- Campaign list (RFC 0005 titles) is the picker for Nueva partida; creating a campaign
  updates it.

## Non-goals

- Run history / past-run outcomes ("Partidas anteriores"), outcome denormalization on
  `SessionRecord`, per-run stats. The menu covers replay in two taps; history can come later.
- Router / deep links. The screen store stays.
- Idle-session reaper (scheduled abandonment) — Revisit triggers.
- Multiplayer, shared campaigns, persistent worlds across runs (RFC 0002 forks stand).
- Changing quota values (3 active / 10 per campaign stay).

## Decision

### Web client: the menu

New `MenuScreen` replaces landing and ritual as the entry screen:

```text
┌────────────────────────────────────┐
│          Dungeon Agent             │
│                                    │
│  [ Tu nombre en la mesa _______ ]  │  (existing GhostField, moved here)
│                                    │
│        Nueva partida               │  primary
│        Continuar                   │  primary; disabled state explains
│        Crear campaña               │  secondary
└────────────────────────────────────┘
```

Flows:

- **Nueva partida** → campaign list screen (RFC 0005 titled cards, loaded on entry) → select
  → opening scroll (docked **Comenzar**) → `startSession` → play. Empty list → guided empty
  state pointing at Crear campaña.
- **Continuar** → `GET /sessions?status=active`:
  - exactly one → resume it directly (below);
  - several → minimal list: campaign title (via the campaign map the client already loads),
    created date, status — plus **Abandonar** per row;
  - none → the action sits disabled on the menu with a one-line reason ("Sin partidas en
    curso"), not an error.
- **Crear campaña** → existing forge: phase theater (humanized per RFC 0005) → on
  `campaign.ready`, land on the new campaign's opening → play. The list fetched on the next
  menu visit includes it — no special "update the list" mechanism beyond loading on entry.
- **Outcome screen** → single CTA "Volver al menú". Replay of the same world is Nueva
  partida → same card: two taps, no dedicated playAgain action.
- **Play screen Salir** (RFC 0005 context bar) → confirm → `abandonSession` → menu.
  Fire-and-forget with one retry: exiting never blocks on the call.

Store/net additions:

- `api.listActiveSessions()` → `GET /sessions?status=active`.
- `api.abandonSession(sessionId)` → `POST /sessions/{id}/abandon`.
- `api.getSessionEvents(sessionId)` → existing events route.
- `gameActions.resumeSession(sessionId)`: fetch record (`GET /sessions/{id}`), replay events
  into `turnLog` (from `turn.completed` payloads, in sequence), restore `expectedRevision`
  and campaign (fetch campaign for the title), re-subscribe the WebSocket from
  `lastEventSequence`, land on `play`. A `READY` session with zero turns resumes to the
  fresh table — no transcript needed.
- `gameActions.abandonSession(sessionId)`: call endpoint, drop it from the local list.
- `Screen` gains `"menu"` (entry) and `"campaigns"` (picker); `"landing"` and `"ritual"` are
  deleted. The forge phases keep `phase`; opening, play, outcome unchanged.

### Backend: `GET /sessions?status=active`

New route on the sessions Lambda. Auth identical to `GET /sessions/{id}`.

- Query the sessions table `ByOwner` GSI for `ownerId = identity.owner_id`, filter to the
  active statuses (same set the quota uses: `REQUESTED / CREATING / READY / ACTIVE`), newest
  `createdAt` first, hard cap 10 (active quota is 3; the cap is hygiene, not pagination).
- Response: `SessionListEnvelope { version: 1, sessions: SessionRecord[] }` — reuse the
  record on the wire.
- Port: `SessionRepository.list_active_by_owner(owner_id) -> tuple[SessionRecord, ...]`;
  memory adapter mirrors the DynamoDB filter.

### Backend: `POST /sessions/{sessionId}/abandon`

New route on the sessions Lambda. Owner-scoped, 404/403 identical to `GET /sessions/{id}`.

- `READY` / `ACTIVE`: transition to `COMPLETED` with outcome `abandoned`, clear
  `active_microvm_id`, terminate the MicroVM (best-effort, log-and-continue as in
  `turns.py` cleanup), emit `session.completed` (`outcome: abandoned`) on the session event
  stream so any subscribed client lands on the outcome screen.
- `REQUESTED` / `CREATING`: `409` retryable — the creation workflow is in flight and would
  race the transition; the client retries once it settles.
- `COMPLETED` / `FAILED`: `200` with the current record — idempotent.
- Effect: the slot frees immediately (`COMPLETED` is outside the active set) and MicroVM cost
  stops at exit.

Note: the `abandoned` literal already exists in `SessionCompletedPayload`; this is the first
control-plane path that emits it. No schema change.

## Alternatives considered

### Continue from localStorage only

Remember `sessionId` in the browser and skip the list endpoint. Rejected: another device, a
cleared cache, or a session that completed while away makes the button lie. The `ByOwner`
query is one index read; do it for real.

### Straight-into-last-session without a menu

Resume automatically on load. Rejected: the menu is the ask, and auto-resume hides Nueva
partida / Crear campaña behind gestures.

### Skip the opening scroll for Nueva partida

Faster, but the opening is the world's first impression and the reason campaigns have
titles. With the docked CTA it costs one tap. Kept.

### Run history instead of Continue-only

Listing finished runs with outcomes needs `outcome` denormalized on `SessionRecord`. Cut for
simplicity; Revisit triggers.

## Consequences

### Positive

- The app opens on what you can do, not on ceremony.
- Closing a tab stops losing the game — the demo killer from RFC 0004 playtests dies.
- The quota/MicroVM leak gets a real fix at exactly the place it becomes visible.
- Two screens (landing, ritual) collapse into one menu; the client shrinks.

### Costs

- Two new routes (list, abandon) with memory-adapter tests; the replay logic lives in the
  client store.
- Resume correctness depends on `turn.completed` payloads staying the transcript source of
  truth (they are today).
- RFC 0005's PR needs its navigation section rebased onto this menu (design system,
  play table, campaign cards, phase humanization all stand).

## Relationship to prior RFCs

- [RFC 0002](0002-campaign-play-split.md): fork semantics and quotas unchanged; sessions stay
  independent per run.
- [RFC 0004](0004-resume-existing-campaign.md): delivers the session-level resume it
  deferred, using the same owner-scoped posture.
- [RFC 0005](0005-web-ux-overhaul.md): supersedes its landing/ritual navigation; keeps its
  design system, play table, campaign cards, docked opening CTA, and error map (which absorbs
  the 429/409 copy).

## Validation criteria

Accept when, against sandbox:

1. Menu shows the three verbs; Continuar is disabled with an explanation when no session is
   active.
2. Start a session, play two turns, refresh the browser → Continuar → the play table shows
   the full transcript and the next turn works (MicroVM rehydrates if needed).
3. Two active sessions → Continuar shows the pick list with campaign titles; Abandonar frees
   the slot (a new session can be created) and the row disappears.
4. Salir from the play table abandons the session: `GET /sessions/{id}` shows `COMPLETED`,
   the MicroVM is terminated, and a subscribed second client sees `session.completed`
   (`abandoned`).
5. Crear campaña completes → opening of the new world → play; the next Nueva partida visit
   lists it with its title.
6. Backend tests: active list (filter, ordering, cap, ownership), abandon transitions
   (ready/active → completed, idempotent repeat, 409 on creating, 403/404 ownership).
7. Client tests/manual: replay builds `turnLog` in sequence with dice results matched by
   `turnId`; resume on a zero-turn `READY` session lands cleanly.

## Revisit triggers

- Orphans still accumulate (clients that never abandon): scheduled idle-session reaper.
- Players ask "how did my last run end?": run history + `outcome` on `SessionRecord` (the
  cut scope, one denormalization away).
- Continue needs the opening too: cache it on resume like `resumeCampaign` does.
- The menu grows a fourth verb (shared campaigns, gallery): its own RFC.

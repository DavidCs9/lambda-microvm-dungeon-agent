# RFC 0005: Web UX Overhaul — Table-First Play, Named Campaigns, New Visual System

- Status: Proposed
- Date: 2026-07-19
- Owner: DavidCs9
- Scope: Frontend redesign of the RFC 0003 client plus a small campaign-record
  denormalization in the control plane

## Summary

A code-level audit of the showcase client (see Appendix) confirms the two pains reported in
playtesting and surfaces more: campaigns are identified only by a UUID suffix, and the play
screen is a growing page that scrolls the action input below the fold. This RFC restructures
the client around where play time actually goes — the play table becomes a fixed-viewport
instrument with a docked composer and an internally scrolling transcript, so **no gameplay
screen ever page-scrolls**. Campaigns get human titles via a small backend denormalization.
The visual identity is rebuilt as a coherent system (tokens, type split, semantic color)
rather than a restyle of the current centered pages.

Lab posture stays: no router, no accounts, no dashboard, no settings screen. Same API spine,
same Pixi atmosphere, same six screens — restructured, not multiplied.

## Context

Findings from the audit (full list in Appendix; file references are `web/src/`):

- **Campaigns have no identity.** `ui/RitualScreen.tsx` renders `…{campaignId.slice(-8)}`
  plus a language badge as the entire list row. Root cause: the campaign wire shape
  (`net/types.ts` `CampaignRecord`) carries no title and no timestamp. The human title exists
  only inside the `OpeningDocument`, one fetch away per campaign. RFC 0004 already flagged
  title denormalization as the follow-up; this is that follow-up.
- **The play table page-scrolls.** `ui/PlayTableScreen.tsx` is one page-flow column: header,
  growing turn log, streaming narration, then the composer pinned with `mt-auto`. After a few
  turns the composer sinks below the fold; there is no internal scroll region, no sticky
  input, no auto-follow of new narration. On mobile with the keyboard open it is twice as bad.
- **No context, no exit.** The play screen shows no campaign title, turn count, or connection
  state (`wsStatus` only appears on the ritual screen), and offers no way to leave —
  `resetToLanding` is wired only on the outcome screen. Closing the tab is the only exit.
- **Dice feedback is modal and tripled.** A roll renders in the Pixi canvas, in a full-screen
  blocking dialog that hides the streaming narration (auto-clear 1.4s *and* click-to-dismiss
  racing), and as a text line in the log. Modality is the problem, not the styling.
- **Machine state leaks into copy.** `ui/PhaseTheaterScreen.tsx` prints raw phase strings
  (`requested`, …) as the screen headline during multi-minute generation, with no steps,
  elapsed time, or cancel. `ErrorLine` prints raw codes like `campaign_creation_failed`,
  positioned under the form — below the fold exactly when things break.
- **Returning players get the worst path.** After RFC 0004 the common case is resume, yet the
  list hides behind a ghost-button click, and a resuming player must scroll the entire opening
  parchment to reach the only "Comenzar la aventura" button at the bottom
  (`ui/OpeningScrollScreen.tsx`).
- **No design system.** Inline hex values (`#e8a07a`) repeat across components; UI chrome and
  story text share one serif; there is no semantic color for success/failure, no `100dvh` or
  safe-area handling, no keyboard submit for the composer.

What works and stays: the Pixi ember/fog atmosphere with per-screen moods, the canvas dice
tumble, the ember palette and Cinzel display face, the one-job-per-screen spine, Spanish copy.

## Goals

- Play table never page-scrolls: fixed `100dvh` shell, internally scrolling transcript,
  composer always visible, at any turn count, desktop and mobile.
- Campaigns are chosen by human title, not UUID.
- Every machine string (phases, error codes) reaches the player only as human copy.
- Dice results are inline transcript beats; nothing ever blocks narration.
- A real design system: semantic tokens, a deliberate serif/sans type split, one component
  vocabulary across all six screens.
- Small backend change: denormalize the opening title onto the campaign record.

## Non-goals

- **Session resume after refresh** (in-memory store loses an in-flight session today).
  Deferred per RFC 0004; see Revisit triggers.
- Campaign deletion, renaming, sharing, gallery, pagination, search.
- Router / deep links / URL state. The screen store stays.
- Auth changes; sandbox `x-player-id` remains.
- Language picker (copy stays Spanish; the hardcoded `"es"` moves to a single constant).
- New backend routes beyond the record shape change; WebSocket/event contracts unchanged.
- Touching MicroVM fork semantics or turn contracts from RFC 0002.

## Decision

### Backend: campaign record gains title and timestamp on the wire

Two additive, backward-compatible changes to the campaign JSON (both the single-get and the
list envelopes):

- `openingTitle: string | null` — denormalized onto the stored record when the opening is
  materialized in the creation workflow (the `MarkCampaignReady` → `EmitCampaignReady`
  sequence in `workflow/campaigns.py` already loads the opening; persist its `title` on the
  record in the same write that marks it ready). `null` for campaigns created before this
  change — no backfill in the lab.
- `createdAt: string` (ISO 8601) — the domain record already has `created_at`; expose it.

Domain model: optional `opening_title: str | None = None` on `CampaignRecord`; validators
unchanged (ready requires artifact refs, not a title). Memory and DynamoDB adapters persist
the new field; DynamoDB items without it deserialize as `null`.

Client fallback rule: `openingTitle ?? "…" + campaignId.slice(-8)`. Old campaigns stay
recognizable, new ones read like stories.

### Frontend: design system

New token layer in `styles.css`, replacing ad-hoc values everywhere:

- Semantic color: keep `--deep/--fog/--ink/--muted/--ember/--line`, add `--success`,
  `--danger` (absorbing the inline `#e8a07a`), and `--surface-1/--surface-2` for panels.
- Type split: **serif is the story, sans is the instrument.** Narration and opening blocks
  stay in Source Serif 4 at 17–18px/1.7. UI chrome — buttons, labels, meta, the composer —
  moves to a system sans stack. Cinzel remains for display titles and dice numerals only.
- Layout primitives: `AppShell` (fixed `100dvh` column with safe-area insets), `Panel`,
  `ContextBar`, `Composer`, `TranscriptEntry`, `DiceChip`, `Card`. Built in `ui/shared.tsx`;
  existing `ScreenShell` survives only for the cinematic screens (landing, outcome).
- Motion: `framer-motion` stays. Full-screen cross-fades stay between cinematic screens;
  within the play table, motion is local (entries fade/slide in, chips pop). Narration keeps
  its natural typewriter feel from streaming.
- Pixi atmosphere: unchanged component; the `play` mood quiets during streaming (lower ember
  rate/alpha) and flares on `dice.rolled`. The canvas dice tumble stays as the ambient,
  non-blocking dice moment.

### Frontend: the play table (the core of this RFC)

`PlayTableScreen` becomes an `AppShell` with three regions; `document.body` does not scroll
on this screen:

```text
┌──────────────────────────────────────────┐
│ ContextBar: ‹ Salir · {openingTitle}     │  fixed, ~48px
│             Turno N · ● conectado        │
├──────────────────────────────────────────┤
│ Transcript (overflow-y: auto, flex-1)    │  internal scroll
│   · narration entries (serif)            │  auto-follows bottom
│   · DiceChip inline per rolled turn      │  "↓ Ir al final" pill
│   · streaming entry at the tail          │  when user scrolled up
├──────────────────────────────────────────┤
│ Composer (docked, safe-area aware)       │  always visible
│   [ auto-growing textarea 1–4 rows ] [↵] │  ⌘/Ctrl+Enter sends
│   error line lives here                  │
└──────────────────────────────────────────┘
```

- **Auto-follow:** transcript sticks to bottom as narration streams; scrolling up pauses
  follow and shows a jump-to-latest pill; returning to bottom resumes follow. Standard chat
  behavior, implemented with a scroll listener plus `IntersectionObserver` on the tail.
- **DiceChip:** `dice.rolled` renders as an inline chip attached to its turn
  (`d20 · 14 — éxito`, semantic color), placed between the player's action echo and the
  narration. The blocking dialog in the current screen is deleted, along with
  `DICE_CLEAR_MS` and `dismissDiceBeat`. The Pixi tumble still plays on the canvas behind.
- **Composer:** textarea grows 1→4 rows then scrolls internally; submit is an inline button
  at the composer edge, not a centered block below it; `Cmd/Ctrl+Enter` submits, `Enter`
  newline; a one-line hint shows the shortcut once. Submit errors render inside the composer
  region, humanized.
- **ContextBar:** opening title (or short-id fallback), turn counter from `turnLog.length`,
  live `wsStatus` dot, and **Salir** — the first exit the play screen has ever had. Salir
  confirms once, then `resetToLanding`. The orphaned session is abandoned server-side, same
  as closing the tab today; session resume is out of scope.
- The decorative "Mesa / Tu turno en la historia" header is deleted. The table is the game,
  not a page about the game.
- Mobile: `100dvh` + `env(safe-area-inset-bottom)`; the docked composer rides above the
  keyboard. No `resize-y` handle on touch.

### Frontend: campaign select (ritual screen rebuild)

- The list loads on entering the screen; no ghost-button reveal. Returning players see their
  campaigns immediately as **cards**: opening title (display face), created date, language,
  ws-agnostic. Short-id only when `openingTitle` is null.
- **Forjar campaña** remains a peer primary action at the top of the list. Empty state
  collapses to today's centered forge prompt.
- Selecting a card goes to the opening scroll as today (`resumeCampaign` unchanged).

### Frontend: phase theater humanization

- Client-side copy map; raw phase strings never render. Campaign example:

  | machine phase  | player copy                                  |
  | -------------- | -------------------------------------------- |
  | `requested`    | Llamando al fuego…                           |
  | `generating_*` | El territorio toma forma…                    |
  | `persisting_*` | Grabando el mundo en la piedra…              |
  | session phases | El MicroVM despierta / Anclando el mundo…    |

  (Final map ships in code keyed to the real `CampaignPhase`/`SessionPhase` enums; unknown
  phases fall back to a generic line, never to the raw string.)
- A simple step row (Forjar → Despertar → Umbral → Mesa) shows where in the spine we are;
  elapsed seconds tick quietly. No cancel in v1 — the forge finishes or fails on its own.

### Frontend: opening scroll

Keep the scroll-reveal for the text — it is the best moment of the current build. Add a
docked bottom bar with **Comenzar la aventura** that is visible from the start; the reveal
no longer gates the exit. For resumed campaigns this removes the forced full scroll.

### Frontend: errors

- Client-side map from error codes/HTTP statuses to human Spanish copy with a recovery hint
  (`campaign_creation_failed` → "El fuego se apagó al forjar. Inténtalo de nuevo."). Unknown
  errors get a generic line; raw codes go to `console` only.
- Errors render adjacent to their action: composer (submit), campaign list (load/resume),
  forge CTA (create). Not at the bottom of a scrolling page.

## Alternatives considered

### N+1 opening fetches for list titles

Frontend-only: fetch every campaign's opening to render titles. Rejected: latency and
complexity on every ritual visit, and RFC 0004 already identified denormalization as the
clean follow-up. The backend change is a handful of lines.

### Player-named campaigns

Ask for a name at forge time. Rejected for v1: adds friction to the one-click forge and
empty/low-effort names are worse than generated titles. The denormalized opening title is
zero-friction; a rename affordance can come later if wanted.

### Keep the dice dialog, restyle it

The dialog's sin is modality — it covers the streaming narration and races two dismissal
mechanics. A prettier dialog still interrupts. Inline chip + ambient Pixi wins.

### Client-only session recovery via localStorage

Persist `sessionId` and re-fetch on load. Out of scope by decision (see Non-goals): it pulls
transcript replay contracts into an already-large frontend RFC.

## Consequences

### Positive

- The screen where ~95% of play time happens stops fighting the player.
- Campaigns become stories ("El umbral de ceniza") instead of hex fragments.
- One token/component system makes the next visual change cheap.
- Backend change is additive; older clients tolerate unknown fields.

### Costs

- Full rewrite of the six screen components plus `shared.tsx`; the store and net layers are
  barely touched (add `openingTitle`/`createdAt` parsing, drop `dismissDiceBeat`).
- Backend: new field through domain model, both persistence adapters, workflow ready-step,
  and serializers; memory-adapter tests updated.
- Campaigns forged before this change keep short-id rows forever (no backfill).
- The design system is a new set of decisions to maintain — the price of the deeper redesign
  the audit calls for.

## Relationship to prior RFCs

- [RFC 0001](0001-web-control-plane.md): HTTP/event/error conventions unchanged; envelopes
  gain fields additively.
- [RFC 0002](0002-campaign-play-split.md): campaign/session semantics untouched.
- [RFC 0003](0003-videogame-web-client.md): stack and atmosphere stand; the screen-by-screen
  presentation is superseded by this RFC.
- [RFC 0004](0004-resume-existing-campaign.md): implements its flagged title-denormalization
  follow-up; resume flow gets the UX it was missing.

## Validation criteria

Accept when, against sandbox:

1. Play table at 20+ turns: `document.body` does not scroll, composer fully visible, new
   narration auto-follows; scrolling up pauses follow and the jump pill works.
2. `GET /campaigns` returns `openingTitle` and `createdAt`; the select screen renders titles
   for new campaigns and short-id fallback for pre-change ones.
3. A dice roll never obscures narration; result visible as an inline chip on its turn.
4. No raw phase string or error code reaches the UI anywhere in the flow (grep the bundle
   for `requested`, `campaign_creation_failed` as rendered copy).
5. iPhone Safari: composer stays above the keyboard; Salir exits to landing; resume flow
   (forge → refresh → select by title → opening → Comenzar) works with the docked CTA.
6. Backend unit tests: record round-trips `opening_title`; ready step persists it; list
   envelope includes it; pre-change items without the field deserialize.

## Revisit triggers

- **Refresh loses the session** becomes the top complaint: session list/resume RFC
  (transcript replay contract), as anticipated by RFC 0004.
- Players want their own campaign names: optional rename; title stays the default.
- Campaign list outgrows one capped page: pagination per RFC 0004's trigger.
- Transcript performance degrades on very long sessions: windowed rendering.

## Appendix: audit findings not repeated above

- Language hardcoded to `"es"` in both create calls (`state/store.ts`); moves to one constant.
- Dice dialog has no focus trap; `aria-live` wraps the whole growing transcript and
  re-announces everything — the new transcript scopes `aria-live` to the streaming tail only.
- `GhostField` player-name input on landing is unlabeled for screen readers beyond its
  eyebrow text; fold into the shared field component.
- `debug.html` lab console is untouched by this RFC.

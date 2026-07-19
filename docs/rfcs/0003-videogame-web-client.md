# RFC 0003: Videogame-Style Browser Client

- Status: Proposed
- Date: 2026-07-19
- Owner: DavidCs9
- Scope: Experimental showcase browser client for the Dungeon Agent control plane

## Summary

This is a lab experiment, not an enterprise product surface. The goal is a browser client that
feels like a game for friend demos — UX first, ceremony last. The existing serverless control
plane from [RFC 0001](0001-web-control-plane.md) and [RFC 0002](0002-campaign-play-split.md)
remains the backend. This RFC defines a pragmatic presentation architecture: Vite + React +
TypeScript with a PixiJS atmosphere layer, Framer Motion for scene transitions, and Tailwind for
layout, driven by the same HTTP and WebSocket contracts already deployed in the sandbox.

Build only what the demo needs. Skip design systems, coverage targets, E2E harnesses, and
process overhead that do not improve what a friend sees and feels. Spanish is the official
player language for the showcase path. The lab prototype under `web/` proved connectivity; this
client replaces that prototype as the UX surface friends can open and play.

## Context

RFC 0001 moved orchestration to API Gateway, Step Functions, DynamoDB, and reconnectable
WebSocket events. RFC 0002 split expensive world and character generation into reusable
campaigns so session start is MicroVM launch plus fork, with zero model calls on the play path.

A minimal Vite + TypeScript page under `web/` already exercises that path: create a Spanish
campaign, watch phases, start a session, submit an action. It is intentionally disposable. The
UI is an operator console (JSON dumps, form chrome, no atmosphere). That is enough to validate
the backend, not enough to showcase the game.

The local Textual TUI remains a frozen reference for presentation contracts (`OpeningView`,
turn narration, dice). New product UX work targets the browser. Friends who try the game will
judge the first viewport, the campaign ritual, the opening scroll, the dice beat, and whether
narration feels authored — not whether the Step Functions graph is correct.

## Goals

- Make the first viewport read as one branded game composition, not a dashboard.
- Drive every setup and play beat from truthful control-plane events over WebSocket.
- Present Spanish campaign openings as a scrollable, ordered ritual matching opening blocks.
- Turn `dice.rolled` into a visible, audible beat before committed narration.
- Stream or reveal narration in step with `narration.delta` / `turn.completed` events.
- Reuse existing `/campaigns` and `/sessions` contracts without changing the control plane.
- Keep atmosphere (canvas) and interaction (DOM) independently replaceable when useful — do not
  over-abstract ahead of a working demo.
- Ship a client friends can run locally against the sandbox with `x-player-id` auth.
- Prefer visible UX wins over infrastructure, process, or test ceremony.

## Non-goals

- Cognito, JWT authorizers, or multi-tenant accounts in this RFC.
- Multiplayer sessions or a public campaign gallery.
- A Phaser (or similar) world simulator with tile maps, physics, or combat arenas.
- Rewriting the control plane, MicroVM rules, or Bedrock adapters.
- Server-side Polly voice in the first shipped client (client-side SFX and ambience only).
- Mandatory static hosting or CDN in v1 (local Vite is enough to accept the RFC).
- Pixel-perfect parity with the Textual TUI layout.
- Enterprise frontend ceremony: design-system packages, storybooks, visual-regression suites,
  coverage gates, Playwright/Cypress matrices, feature-flag platforms, or CI jobs whose only job
  is to certify the SPA.
- Perfect module boundaries, exhaustive state machines, or speculative abstractions before the
  happy path feels good to play.

## Decision

### Lab posture

Treat the client as an experiment. Ship the UX spine end-to-end, then polish what a friend
notices. If a choice adds ceremony without improving the demo, do not take it. Manual play
against the live sandbox is the primary validation; automated client tests are optional and
should stay minimal if added at all.

### Product shape

The showcase client is narrative TTRPG theater: landing, campaign creation ritual, phase
theater, opening scroll, play table, dice beat, narration. It is not an arcade engine and not a
settings dashboard. One job per screen. The first viewport holds brand, one headline, one short
supporting line, one CTA group, and one dominant atmospheric plane.

### Stack

| Layer | Choice | Role |
|-------|--------|------|
| App shell | Vite + React 19 + TypeScript | Screens, forms, event-driven UI |
| Atmosphere | PixiJS canvas behind the UI | Parallax, particles, vignette, dice stage |
| Motion | Framer Motion | Phase transitions, opening reveals, UI beats |
| Styling | Tailwind + expressive fonts | Layout and typography; avoid default SaaS themes |
| Network | Thin HTTP + WebSocket client | Evolved from lab `api.ts` / `ws.ts` |
| Audio (v1) | Web Audio + static SFX/ambience | Dice and tavern bed; no Polly yet |

React owns interaction and accessibility. PixiJS owns the non-DOM spectacle layer. They share a
single event-derived store; Pixi does not own networking or game rules.

### Topology

```text
Browser
  |-- React UI (landing, ritual, opening, play table)
  |-- PixiJS stage (atmosphere, dice, vignette)
  |-- HTTPS --> API Gateway /campaigns /sessions   (RFC 0002)
  |-- WSS   --> subscribe campaign|session events  (RFC 0001)
```

One control plane deployment. The client is a static SPA that can be developed with Vite and
later hosted independently of the SAM stack.

### UX spine

```text
Landing (brand hero)
  -> Create campaign ritual
  -> Phase theater (WebSocket campaign events)
  -> Opening scroll (Spanish blocks from campaign.ready)
  -> Play table (log + action)
  -> Dice beat (dice.rolled)
  -> Narration (narration.delta / turn.completed)
```

Sandbox identity stays `x-player-id` (and WebSocket `playerId`) for lab demos. Official create
requests send `language: "es"`.

### Client module layout

Under `web/`, absorb and then replace the lab v0 surface:

```text
web/src/
  game/     Pixi stage, dice, particles, atmosphere
  ui/       React screens and Framer Motion transitions
  net/      HTTP and WebSocket adapters (from api.ts / ws.ts)
  state/    Campaign and session store keyed by event sequence
  assets/   Fonts, SFX, ambience, textures
```

Lab v0 files remain until the showcase screens cover the same happy path; then they are removed
or reduced to a debug route. Fold folders when the code is small; do not invent layers for
symmetry.

### Event to presentation mapping

Sequenced envelopes remain the source of truth. Reconnect uses `afterSequence` as today. Map
only the events the demo needs; ignore or soft-handle the rest until a friend hits a gap.

| Event | Presentation beat |
|-------|-------------------|
| `campaign.creation.started` | Ritual begins; phase theater visible |
| `campaign.phase.changed` | Named phase label and progress motion |
| `campaign.ready` | Transition to opening scroll; load blocks |
| `campaign.creation.failed` | Recoverable failure copy; allow retry |
| `session.creation.started` | Play setup theater |
| `session.phase.changed` | MicroVM / init phases |
| `session.ready` | Enter play table with opening / snapshot |
| `session.creation.failed` | Failure copy; return to campaign |
| `turn.started` | Lock input; show pending turn |
| `dice.rolled` | Dice theater + SFX before final narration |
| `narration.delta` | Append streaming narration |
| `turn.completed` | Unlock input; update revision |
| `session.completed` | Terminal outcome screen |

The client never treats model output as final before MicroVM-backed outcomes. Dice and
committed narration follow the control-plane order from RFC 0001.

### Auth and language

- v1 auth: sandbox `x-player-id` / `playerId` only.
- Showcase language: Spanish (`es`) as the default and official demo path.
- English remains a supported control-plane locale but is not the hero path for demos.

## Alternatives considered

### Pure React without a canvas layer

Fastest to ship, but friends will feel a form app. Atmosphere, dice theater, and vignette either
become heavy DOM hacks or get skipped. Rejected for a showcase client.

### Phaser (or a full game engine) as the shell

Wrong primary tool for a text-first TTRPG. Forms, opening scroll, and accessibility fight the
engine. Pixi as a subordinate atmosphere layer keeps spectacle without owning the app.

### Next.js SSR

No SEO or authenticated SSR requirement for a lab sandbox SPA. Extra framework surface for no
gameplay benefit. Vite SPA stays.

### Dashboard-style control UI

Multi-panel admin chrome undermines the product. The first viewport must pass the brand test:
remove the nav and it should still be recognizable as this game.

## Consequences

### Positive

- Demos can start from a browser without explaining JSON or Step Functions.
- Presentation can iterate without redeploying the control plane.
- Clear split: React for interaction, Pixi for spectacle, events for truth.
- Lab v0 remains a fallback until the showcase path is complete.

### Costs

- Heavier frontend dependencies and an asset pipeline for fonts, textures, and SFX.
- Two visual systems (DOM + canvas) need a rough shared look, not a formal design system.
- Showcase polish takes more design attention than the lab console.
- Sandbox auth is still unsuitable for a public product until Cognito lands.
- Deliberate under-investment in client test and process ceremony; bugs may be found by playing.

## Relationship to RFC 0001 and RFC 0002

RFC 0001 remains accepted for transport, durable events, turn execution, and MicroVM authority.
RFC 0002 remains the campaign and play split (`POST /campaigns`, `POST /sessions` with
`campaignId`, fork semantics).

This RFC does not change those backend contracts. It defines how a browser presents them. When
voice streaming or authenticated multi-user access is required, those revisit triggers may spawn
follow-up RFCs; they are not required to accept this one. Do not add RFC or CI ceremony for the
client unless a revisit trigger forces it.

## Validation criteria

Acceptance is a manual friend demo, not a green frontend CI matrix. The showcase client is
validated when one friend can, without reading JSON:

1. open the app and recognize a branded game in the first viewport;
2. create a Spanish campaign and see truthful creation phases;
3. read the opening as an ordered scroll of world and protagonist;
4. start a session against that campaign and reach a playable table;
5. submit a free-form action and see a dice beat before committed narration;
6. reconnect or refresh and resume from sequenced events without a broken UI;
7. complete or fail a session with a clear terminal outcome screen.

Optional smoke scripts or a few unit checks are fine if they save time. They are not a gate to
ship the experiment.

## Revisit triggers

- Public or multi-user demos need real auth: introduce Cognito or JWT as a separate change.
- Spoken narration is required: wire Polly (or equivalent) to the same opening and turn blocks.
- Campaigns should be shared between friends: sharing and authorization as a separate RFC.
- Adventure art should drive the Pixi stage: optional generative or curated scene assets.
- Static hosting becomes the default demo path: add a minimal S3/CloudFront (or similar) publish
  step without changing the client architecture.
- The experiment becomes a real product: only then reconsider enterprise testing, auth, and
  hosting ceremony — not before.

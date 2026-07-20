# RFC 0007: Live Polly Narrator — Spoken Dungeon Master in the Web Client

- Status: Proposed
- Date: 2026-07-19
- Owner: DavidCs9
- Scope: Bring the TUI's Amazon Polly spoken narration to the web client via a
  control-plane speech path; reuse existing synthesizer contracts and opening
  `narratable` blocks; speak turn narration from `narration.delta` by sentence

## Summary

Restore the best part of the Textual TUI demo: the Dungeon Master **speaks** while you play.
The web client already streams narration text and plays tavern ambience; it never hears the
story. This RFC wires Amazon Polly so opening blocks and turn narration are spoken aloud in
the same order the player reads them — same bilingual voices as the TUI (`Matthew` / `Andres`,
generative engine), music ducks under speech, voice can be muted without touching game state.

For turns, speech starts **while text is still streaming**: the client splits `narration.delta`
into finished sentences, requests Polly per sentence, and plays them in a queue so the DM
begins talking as soon as the first sentence lands — not after `turn.completed`. That is the
UX win over the TUI's speak-everything-at-once model.

Lab posture: one speech endpoint, content-hash cache in S3, short-lived playback URLs, client
sentence queue. No true streaming TTS codec, no voice picker UI, no separate audio microservice.
Polly credentials stay in Lambda; MicroVMs still never see them.

## Context

Why this mattered in the TUI:

- After each turn (and the opening scene), `LocalAudioExperience.narrate` synthesized with
  Polly and played while pausing the tavern loop (`src/dungeon_agent/audio/local.py`).
- F4 toggled voice; failure was silent — gameplay never blocked on TTS.
- The spoken DM turned a text log into a tabletop session. Friends remembered the voice more
  than the layout.

What the web has today:

- RFC 0003 shipped client-side SFX + ambience only and listed Polly as a revisit trigger.
- `web/src/game/audio.ts` unlocks Web Audio, loops the inn track, plays dice tones — no speech.
- Opening documents already carry `narratable` per block (`OpeningBlock`); the store preserves
  that flag. Turn narration arrives as `narration.delta` then a final complete string on
  `turn.completed`.
- `PollySpeechSynthesizer` already caches by `engine|voice|language|text` hash
  (`src/dungeon_agent/audio/polly.py`). The TUI used a local disk cache; the web needs the same
  idea behind an authenticated API.

Why deltas (not wait-for-complete):

- Bedrock already streams visible text; waiting for `turn.completed` leaves a silent gap while
  the player is reading. Speaking the first finished sentence overlaps synthesis of later ones
  with reading time — the session feels live.
- Polly generative is utterance-oriented, not a token stream. Feeding raw tiny deltas would
  sound broken and multiply cost. **Sentence-bounded** chunks are the sweet spot: early start,
  natural prosody, still one `/speech` call per phrase.

Known debt from RFC 0001: the TUI rendered the full opening but sent only `opening.scene` to
Polly, so eyes and ears diverged. The web path must narrate **every** `narratable: true` block
in document order, then the turn text the player sees — never a separately assembled script.

## Goals

- Spoken DM during opening scroll and every live turn, using the exact visible text.
- Turn speech begins on the first completed sentence from `narration.delta`, not only after
  `turn.completed`.
- Same voice map and engine as the TUI for continuity (`en` → Matthew, `es` → Andres,
  `generative`).
- Duck / pause ambience while speech plays; resume after.
- Player can mute voice (and optionally skip the current clip) without mutating session state.
- TTS failure never blocks play, dice, or transcript.
- Reconnect / Continuar (RFC 0006) does **not** auto-replay old speech; only new opening
  playback (first visit) and newly streamed turns speak.
- MicroVMs and the browser never hold Polly credentials.

## Non-goals

- True streaming TTS (chunked audio frames / WebSocket PCM as tokens arrive).
- Synthesizing every raw `narration.delta` fragment (too small / unstable for Polly).
- Bidirectional voice input / speech-to-text actions.
- Per-user voice picker, SSML authoring, or Neural vs generative A/B UI.
- Client-side Polly (browser SDK with user credentials).
- Changing Bedrock narration quality, prompts, or the text streaming path.
- Enterprise audio ops: multi-region failover, CDN invalidation ceremony, waveform UI.

## Decision

### Playback model (client)

Extend `web/src/game/audio.ts` (or a thin sibling) with a **narration queue**:

1. After audio unlock (existing gesture), voice defaults **on**.
2. Opening: enqueue each block where `narratable === true`, in order; speak sequentially
   (blocks are already sentence-scale; no delta path).
3. Play table — **sentence-from-deltas**:
   - Append each `narration.delta` to a turn buffer (same string the UI shows).
   - Whenever the buffer yields one or more **finished sentences**, dequeue them, `POST /speech`
     per sentence, and enqueue playback in order.
   - Prefetch is allowed: request speech for sentence N+1 while N is still playing.
   - On `turn.completed`, flush any trailing remainder that never hit a sentence boundary
     (must equal the suffix of the final `narration` not yet spoken). If the reassembled
     spoken sentences + remainder !== final narration, prefer the final narration for the
     unspoken tail only — never re-speak already queued sentences.
4. While a clip plays, duck or pause the inn loop (mirror TUI `_speaking` behavior).
5. Mute stops the current clip and clears the pending queue + turn sentence buffer; unmute
   applies to future items.
6. Skip advances to the next queued item (optional chrome control; mute alone is enough for v1).

Autoplay policy: speech only after the same unlock path used for ambience. If unlock never
happened, queue silently no-ops until the next gesture.

### Sentence splitting (lab-simple)

Client-side, language-aware enough for `en` / `es`:

- A sentence completes on `.` `!` `?` `…` (and Spanish `¡`/`¿` openers stay attached to the
  following sentence).
- Do not emit a sentence shorter than ~12 characters after trim (avoid "Sí." storms); hold
  until the next boundary or `turn.completed` flush.
- Do not synthesize mid-word: only split after a boundary that already appears in the visible
  buffer (deltas may end mid-sentence — wait).

No NLP library. If playtests show bad splits (abbreviations, decimals), tighten the heuristic
in the client only.

### Speech API (control plane)

Add one authenticated route, ownership-scoped like other session/campaign reads:

```http
POST /speech
Content-Type: application/json

{
  "text": "<one sentence or opening block>",
  "language": "es" | "en"
}
```

Response (cache hit or after Polly):

```json
{
  "url": "https://…presigned GET…",
  "expiresInSeconds": 300,
  "cacheHit": true
}
```

Behavior:

- Normalize nothing beyond what `PollySpeechSynthesizer` already keys on (raw text + language +
  voice + engine). Displayed text === spoken text.
- Cache object key = content hash; store MP3 in a dedicated prefix/bucket (lab: reuse an
  existing app bucket with `speech/` prefix if one already holds static assets).
- On miss: Lambda calls Polly `synthesize_speech` (same params as TUI), writes MP3, returns
  presigned GET.
- Cap text length to the narration contract max (4_000). Reject empty / oversize with 400.
- Rate-limit per owner (cheap lab guard): soft cap that still allows several sentences per
  turn (e.g. tens of `/speech` calls per minute), so a buggy client cannot spin Polly.

No WebSocket audio frames. No embedding base64 in events (keeps event payloads small and
avoids replaying speech on reconnect storm).

### Shared synthesizer

Lift or call the existing `PollySpeechSynthesizer` from the control-plane Lambda package so
TUI and web do not drift on engine/voice/hash. Disk cache becomes S3; the hash formula stays.

Infra (CDK, mínimo):

- IAM `polly:SynthesizeSpeech` on the speech Lambda only.
- S3 put/get on the speech cache prefix; presign GET with short TTL (5 minutes is enough).
- Optional CloudWatch metric: synthesis latency + cache hit ratio — no narration text in logs
  (same privacy rule as RFC 0001).

### UI chrome

- One voice toggle on the play table (and opening if ambient chrome exists) — label from
  locale (`voice` / `voz`), parallel to TUI F4.
- No settings screen. Preference may live in `localStorage` for the tab; server does not store
  it.

### Sync rules (non-negotiable)

| Surface | Spoken source |
|---------|----------------|
| Opening | Each `OpeningBlock` with `narratable: true`, document order |
| Turn | Sentences extracted from the live `narration.delta` buffer, then trailing flush on `turn.completed` |
| Suggestions / dice chrome | Never spoken |
| Resume / event replay | Never auto-spoken |

Checksum rule: concatenating spoken turn sentences (in order) must equal the final
`turn.completed` narration. If the stream aborts incomplete, speak only what was finalized as
sentences plus any explicit remainder on the completed/failed terminal event; do not invent
text.

## Alternatives considered

### Speak only on `turn.completed` (TUI parity)

Simplest, one Polly call per turn. Rejected as default: the web already streams text, so
waiting wastes the live feel. Kept as **automatic fallback** when voice is enabled but the
turn emits no deltas (non-streaming path) — then enqueue the full final narration once.

### Synthesize every raw delta

Rejected: fragments are not utterances; prosody breaks; cache keys explode; cost spikes.

### True streaming TTS / WebSocket audio

Rejected for lab scope. Sentence prefetch already overlaps Bedrock stream with Polly+playback.
Revisit only if first-sentence latency is still too high after cache warm.

### Attach speech URLs to WebSocket events

Synthesize inside the turn workflow and push URLs with deltas. Rejected for v1: couples turn
orchestration to Polly, burns synthesis for muted clients, complicates reconnect. Pull-on-demand
keeps mute cheap.

### Browser calls Polly with temporary credentials

Rejected: credential surface and CORS/session complexity for a lab demo. One Lambda is enough.

### Third-party TTS instead of Polly

Rejected for continuity: the remembered experience *is* Polly generative with these voices.
Swap only if Polly becomes unavailable or cost-prohibitive (Revisit).

## Consequences

### Positive

- Web demo recovers the TUI’s strongest emotional beat — and improves it: the DM talks *as*
  the story appears.
- Opening ears match opening eyes (fixes the RFC 0001 divergence for the new client).
- Sentence cache hits often (short repeated phrases); mute still avoids work after cancel.
- Mute / failure isolation preserves the table-first UX from RFC 0005.

### Costs

- More `/speech` calls per turn (typically 1–3 short sentences vs one blob). Mitigated by hash
  cache and small payloads.
- Client owns split + queue correctness (tests for boundary flush and checksum).
- First-sentence latency still includes one Polly round-trip on cache miss (prefetch helps
  sentence 2+).
- One more Lambda permission surface and cache lifecycle (lab can expire speech objects after
  N days).

## Relationship to prior RFCs

- [RFC 0001](0001-web-control-plane.md): implements the “Introduction and audio synchronization”
  rule (same blocks / same visible text, same order; audio never mutates game state). MicroVM
  credential boundary unchanged. Aligns with the Bedrock `narration.delta` streaming lab: ears
  follow the same stream eyes already use.
- [RFC 0003](0003-videogame-web-client.md): satisfies the revisit trigger “Spoken narration is
  required”; supersedes the Audio (v1) “no Polly yet” row for the showcase client.
- [RFC 0005](0005-web-ux-overhaul.md): voice toggle sits in the play-table chrome; speech must
  not introduce modal overlays over the transcript.
- [RFC 0006](0006-main-menu-navigation.md): Continuar / event replay must not flood Polly;
  only live forward playback speaks.

## Validation criteria

Accept when, against sandbox:

1. Create/open a Spanish campaign: narratable opening blocks play in order with Andres;
   possible-action chips stay silent.
2. English session uses Matthew; switching language on a new campaign switches voice.
3. Submit a turn with streaming narration: **before** `turn.completed`, the first finished
   sentence is requested from `/speech` and begins playing; later sentences follow in order;
   ambience ducks then returns.
4. Spoken concatenation for that turn equals the final `narration` string.
5. Mute mid-stream: current clip stops, queue + sentence buffer clear; further deltas stay
   silent until unmute (unmute does not backfill the muted turn).
6. Kill Polly / force 5xx from `/speech`: transcript and next turn still work; no error modal
   required (optional quiet status is fine).
7. Refresh → Continuar: transcript rebuilds; **no** speech storm from history; the next new
   turn speaks from its deltas normally.
8. Identical sentence twice: second `/speech` is a cache hit without a second Polly call.
9. Fallback: a turn with only `turn.completed` (no deltas) still speaks the full narration once.
10. Unit tests: sentence splitter (mid-delta hold, min length, trailing flush); ownership on
    `/speech`; oversize text rejected.

## Revisit triggers

- First-sentence wait still feels slow on cold cache: speculative synthesize of the first
  N characters is rejected (desync risk); consider warmer cache, Neural engine for short
  lines, or true streaming TTS.
- Splitter botches abbreviations / dialogue: improve heuristics or flush on `;` / em-dash.
- Cache + Polly cost grows with public demos: longer TTL CDN in front of speech objects, or
  stricter rate limits.
- Players want a different DM timbre: small voice map config, still server-side.
- Bidirectional voice commands: separate RFC; do not overload `/speech`.

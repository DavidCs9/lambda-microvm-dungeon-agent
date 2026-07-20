/**
 * Web Audio dice SFX + procedural fantasy soundtrack.
 * No binary assets — pads, bass, and a sparse motif over a Dm loop.
 */

let ctx: AudioContext | null = null;
let soundtrack: { gain: GainNode; stop: () => void } | null = null;
let unlocked = false;

/** Concert A4 reference. */
const A4 = 440;

function midiToHz(midi: number): number {
  return A4 * 2 ** ((midi - 69) / 12);
}

function getCtx(): AudioContext {
  if (!ctx) {
    ctx = new AudioContext();
  }
  return ctx;
}

/** Resume context after a user gesture (autoplay policy). */
export async function unlockAudio(): Promise<void> {
  const c = getCtx();
  if (c.state === "suspended") {
    await c.resume();
  }
  unlocked = true;
  if (!soundtrack) {
    startSoundtrack();
  }
}

function tone(
  c: AudioContext,
  freq: number,
  start: number,
  dur: number,
  type: OscillatorType,
  peak: number,
  dest: AudioNode,
): void {
  const osc = c.createOscillator();
  const g = c.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  g.gain.setValueAtTime(0.0001, start);
  g.gain.exponentialRampToValueAtTime(peak, start + 0.012);
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  osc.connect(g);
  g.connect(dest);
  osc.start(start);
  osc.stop(start + dur + 0.02);
}

/** Short dice click / tumble / land. Call after unlock or it resumes first. */
export async function playDiceSfx(success: boolean): Promise<void> {
  await unlockAudio();
  const c = getCtx();
  const master = c.createGain();
  master.gain.value = 0.35;
  master.connect(c.destination);

  const t0 = c.currentTime;
  for (let i = 0; i < 5; i++) {
    const f = 180 + Math.random() * 220 + i * 40;
    tone(c, f, t0 + i * 0.045, 0.06, "triangle", 0.22, master);
  }
  const land = t0 + 0.28;
  tone(c, success ? 320 : 140, land, 0.18, "sine", 0.4, master);
  tone(c, success ? 640 : 90, land + 0.02, 0.12, "square", 0.12, master);
  if (success) {
    tone(c, 880, land + 0.08, 0.25, "sine", 0.15, master);
  }
}

/**
 * Soft fantasy loop in D minor:
 * i–VI–III–VII (Dm · Bb · F · C), warm pads, pulse bass, sparse harp motif.
 */
function startSoundtrack(): void {
  if (soundtrack || !ctx) return;
  const c = ctx;

  const master = c.createGain();
  master.gain.value = 0;
  master.connect(c.destination);
  // Gentle fade-in so the first gesture does not slam the score.
  master.gain.linearRampToValueAtTime(0.11, c.currentTime + 2.4);

  const bus = c.createGain();
  bus.gain.value = 1;
  bus.connect(master);

  // Warm low shelf + soft ceiling so pads stay under the narration.
  const filter = c.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = 2400;
  filter.Q.value = 0.5;
  filter.connect(bus);

  const padGain = c.createGain();
  padGain.gain.value = 0.22;
  padGain.connect(filter);

  const bassGain = c.createGain();
  bassGain.gain.value = 0.28;
  bassGain.connect(filter);

  const motifGain = c.createGain();
  motifGain.gain.value = 0.09;
  motifGain.connect(filter);

  // Simple feedback delay for the motif (hall feel, not muddy).
  const delay = c.createDelay(1.5);
  delay.delayTime.value = 0.42;
  const delayFeedback = c.createGain();
  delayFeedback.gain.value = 0.28;
  const delayWet = c.createGain();
  delayWet.gain.value = 0.35;
  motifGain.connect(delay);
  delay.connect(delayFeedback);
  delayFeedback.connect(delay);
  delay.connect(delayWet);
  delayWet.connect(filter);

  type Voice = { osc: OscillatorNode; gain: GainNode };
  const voices: Voice[] = [];
  const timers: number[] = [];

  function startVoice(
    freq: number,
    type: OscillatorType,
    dest: AudioNode,
    detuneCents = 0,
  ): Voice {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    osc.detune.value = detuneCents;
    gain.gain.value = 0.0001;
    osc.connect(gain);
    gain.connect(dest);
    osc.start();
    const voice = { osc, gain };
    voices.push(voice);
    return voice;
  }

  // Chord tones as MIDI: Dm · Bb · F · C  (root + third + fifth + optional 7th color)
  const progression: number[][] = [
    [50, 53, 57, 60], // Dm: D3 F3 A3 C4
    [46, 50, 53, 58], // Bb: Bb2 D3 F3 Bb3
    [53, 57, 60, 65], // F:  F3 A3 C4 F4
    [48, 52, 55, 60], // C:  C3 E3 G3 C4
  ];

  // Motif over D minor pentatonic — sparse, leaves space for dialogue.
  const motifMidi = [62, 65, 69, 67, 65, 62, 60, 57, 60, 62];
  let chordIndex = 0;
  let motifIndex = 0;

  // Three pad voices (slightly detuned for width) + one bass.
  const padVoices = [
    startVoice(midiToHz(50), "sine", padGain, -6),
    startVoice(midiToHz(53), "sine", padGain, 4),
    startVoice(midiToHz(57), "triangle", padGain, -3),
    startVoice(midiToHz(60), "sine", padGain, 7),
  ];
  const bass = startVoice(midiToHz(38), "sine", bassGain, 0);

  // Slow breath on the pad bus.
  const breath = c.createOscillator();
  const breathGain = c.createGain();
  breath.type = "sine";
  breath.frequency.value = 0.045;
  breathGain.gain.value = 0.06;
  breath.connect(breathGain);
  breathGain.connect(padGain.gain);
  breath.start();
  voices.push({ osc: breath, gain: breathGain });

  function glideVoice(voice: Voice, hz: number, when: number, dur = 1.8): void {
    voice.osc.frequency.cancelScheduledValues(when);
    voice.osc.frequency.setValueAtTime(Math.max(voice.osc.frequency.value, 1), when);
    voice.osc.frequency.exponentialRampToValueAtTime(Math.max(hz, 1), when + dur);
    voice.gain.gain.cancelScheduledValues(when);
    const peak = voice === bass ? 0.55 : 0.32;
    voice.gain.gain.setValueAtTime(Math.max(voice.gain.gain.value, 0.0001), when);
    voice.gain.gain.exponentialRampToValueAtTime(peak, when + 0.9);
    voice.gain.gain.exponentialRampToValueAtTime(peak * 0.72, when + dur);
  }

  function applyChord(index: number, when: number): void {
    const chord = progression[index % progression.length];
    for (let i = 0; i < padVoices.length; i++) {
      glideVoice(padVoices[i], midiToHz(chord[i]), when, 2.2);
    }
    // Bass follows the root an octave down.
    glideVoice(bass, midiToHz(chord[0] - 12), when, 2.4);
  }

  function pluckMotif(when: number): void {
    const midi = motifMidi[motifIndex % motifMidi.length];
    motifIndex += 1;
    // Skip some beats so it never chatters over the table.
    if (motifIndex % 5 === 0) {
      return;
    }
    const osc = c.createOscillator();
    const g = c.createGain();
    osc.type = "triangle";
    osc.frequency.value = midiToHz(midi);
    g.gain.setValueAtTime(0.0001, when);
    g.gain.exponentialRampToValueAtTime(0.55, when + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, when + 1.6);
    osc.connect(g);
    g.connect(motifGain);
    osc.start(when);
    osc.stop(when + 1.7);
  }

  // Seed first chord immediately.
  applyChord(0, c.currentTime + 0.05);

  // Advance progression every ~10s; motif every ~2.6s (with skips).
  const chordMs = 10_000;
  const motifMs = 2_600;
  timers.push(
    window.setInterval(() => {
      if (!ctx) return;
      chordIndex = (chordIndex + 1) % progression.length;
      applyChord(chordIndex, ctx.currentTime + 0.02);
    }, chordMs),
  );
  timers.push(
    window.setInterval(() => {
      if (!ctx) return;
      pluckMotif(ctx.currentTime + 0.02);
    }, motifMs),
  );

  soundtrack = {
    gain: master,
    stop: () => {
      for (const id of timers) {
        window.clearInterval(id);
      }
      timers.length = 0;
      const now = c.currentTime;
      try {
        master.gain.cancelScheduledValues(now);
        master.gain.setValueAtTime(master.gain.value, now);
        master.gain.linearRampToValueAtTime(0.0001, now + 0.4);
      } catch {
        /* context may already be closed */
      }
      window.setTimeout(() => {
        for (const voice of voices) {
          try {
            voice.osc.stop();
          } catch {
            /* already stopped */
          }
        }
        voices.length = 0;
        try {
          master.disconnect();
        } catch {
          /* already disconnected */
        }
      }, 450);
    },
  };
}

export function stopAmbience(): void {
  soundtrack?.stop();
  soundtrack = null;
}

export function disposeAudio(): void {
  stopAmbience();
  if (ctx) {
    void ctx.close();
    ctx = null;
  }
  unlocked = false;
}

export function isAudioUnlocked(): boolean {
  return unlocked;
}

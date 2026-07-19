/** Web Audio dice SFX + low tavern ambience. Procedural — no binary assets. */

let ctx: AudioContext | null = null;
let ambienceNodes: { gain: GainNode; stop: () => void } | null = null;
let unlocked = false;

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
  if (!ambienceNodes) {
    startAmbience();
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
  // tumble clicks
  for (let i = 0; i < 5; i++) {
    const f = 180 + Math.random() * 220 + i * 40;
    tone(c, f, t0 + i * 0.045, 0.06, "triangle", 0.22, master);
  }
  // land thump
  const land = t0 + 0.28;
  tone(c, success ? 320 : 140, land, 0.18, "sine", 0.4, master);
  tone(c, success ? 640 : 90, land + 0.02, 0.12, "square", 0.12, master);
  if (success) {
    tone(c, 880, land + 0.08, 0.25, "sine", 0.15, master);
  }
}

function startAmbience(): void {
  if (ambienceNodes || !ctx) return;
  const c = ctx;
  const master = c.createGain();
  master.gain.value = 0.045;
  master.connect(c.destination);

  const oscA = c.createOscillator();
  const oscB = c.createOscillator();
  const gA = c.createGain();
  const gB = c.createGain();
  const filter = c.createBiquadFilter();

  oscA.type = "sine";
  oscB.type = "sine";
  oscA.frequency.value = 55;
  oscB.frequency.value = 82.5;
  gA.gain.value = 0.7;
  gB.gain.value = 0.35;
  filter.type = "lowpass";
  filter.frequency.value = 180;

  // slow ember shimmer via LFO on filter
  const lfo = c.createOscillator();
  const lfoGain = c.createGain();
  lfo.type = "sine";
  lfo.frequency.value = 0.07;
  lfoGain.gain.value = 40;
  lfo.connect(lfoGain);
  lfoGain.connect(filter.frequency);

  oscA.connect(gA);
  oscB.connect(gB);
  gA.connect(filter);
  gB.connect(filter);
  filter.connect(master);

  oscA.start();
  oscB.start();
  lfo.start();

  ambienceNodes = {
    gain: master,
    stop: () => {
      try {
        oscA.stop();
        oscB.stop();
        lfo.stop();
      } catch {
        /* already stopped */
      }
      master.disconnect();
    },
  };
}

export function stopAmbience(): void {
  ambienceNodes?.stop();
  ambienceNodes = null;
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

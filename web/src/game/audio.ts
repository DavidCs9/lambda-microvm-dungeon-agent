/**
 * Dice SFX (Web Audio) + tavern soundtrack (CC0 MP3 loop).
 *
 * Track: "Medieval: The Old Tower Inn" by RandomMind — CC0
 * https://opengameart.org/content/medieval-the-old-tower-inn
 */

const SOUNDTRACK_URL = "/audio/the-old-tower-inn.mp3";
/** Keep music under the dialogue; dice stay punchier on their own bus. */
const SOUNDTRACK_VOLUME = 0.32;

let ctx: AudioContext | null = null;
let soundtrackEl: HTMLAudioElement | null = null;
let unlocked = false;

function getCtx(): AudioContext {
  if (!ctx) {
    ctx = new AudioContext();
  }
  return ctx;
}

function getSoundtrack(): HTMLAudioElement {
  if (!soundtrackEl) {
    const el = new Audio(SOUNDTRACK_URL);
    el.loop = true;
    el.preload = "auto";
    el.volume = SOUNDTRACK_VOLUME;
    soundtrackEl = el;
  }
  return soundtrackEl;
}

/** Resume context + start the tavern loop after a user gesture (autoplay policy). */
export async function unlockAudio(): Promise<void> {
  const c = getCtx();
  if (c.state === "suspended") {
    await c.resume();
  }
  unlocked = true;
  const track = getSoundtrack();
  try {
    if (track.paused) {
      await track.play();
    }
  } catch (error) {
    console.warn("soundtrack play blocked", error);
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

export function stopAmbience(): void {
  if (!soundtrackEl) {
    return;
  }
  soundtrackEl.pause();
  soundtrackEl.currentTime = 0;
}

export function disposeAudio(): void {
  stopAmbience();
  if (soundtrackEl) {
    soundtrackEl.src = "";
    soundtrackEl = null;
  }
  if (ctx) {
    void ctx.close();
    ctx = null;
  }
  unlocked = false;
}

export function isAudioUnlocked(): boolean {
  return unlocked;
}

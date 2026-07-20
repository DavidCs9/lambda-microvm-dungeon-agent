/**
 * Dice SFX (Web Audio) + tavern soundtrack (CC0 MP3 loop) + Polly speech queue.
 *
 * Track: "Medieval: The Old Tower Inn" by RandomMind — CC0
 * https://opengameart.org/content/medieval-the-old-tower-inn
 */

const SOUNDTRACK_URL = "/audio/the-old-tower-inn.mp3";
/** Keep music under the dialogue; dice stay punchier on their own bus. */
const SOUNDTRACK_VOLUME = 0.32;
const VOICE_KEY = "dungeon-agent-voice";

let ctx: AudioContext | null = null;
let soundtrackEl: HTMLAudioElement | null = null;
let unlocked = false;
const unlockListeners = new Set<() => void>();

let voiceEnabled = loadVoiceEnabled();
let speechQueue: string[] = [];
let speechPlaying = false;
let currentSpeechEl: HTMLAudioElement | null = null;
let soundtrackPausedForSpeech = false;

function loadVoiceEnabled(): boolean {
  try {
    const stored = localStorage.getItem(VOICE_KEY);
    if (stored === "0" || stored === "false") {
      return false;
    }
  } catch {
    // ignore
  }
  return true;
}

function persistVoiceEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(VOICE_KEY, enabled ? "1" : "0");
  } catch {
    // ignore
  }
}

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

function notifyUnlockListeners(): void {
  for (const listener of unlockListeners) {
    listener();
  }
}

/** Subscribe to the first successful audio unlock (gesture). */
export function onAudioUnlock(listener: () => void): () => void {
  unlockListeners.add(listener);
  if (unlocked) {
    listener();
  }
  return () => {
    unlockListeners.delete(listener);
  };
}

/** Resume context + start the tavern loop after a user gesture (autoplay policy). */
export async function unlockAudio(): Promise<void> {
  const c = getCtx();
  if (c.state === "suspended") {
    await c.resume();
  }
  const wasUnlocked = unlocked;
  unlocked = true;
  const track = getSoundtrack();
  try {
    if (track.paused) {
      await track.play();
    }
  } catch (error) {
    console.warn("soundtrack play blocked", error);
  }
  if (!wasUnlocked) {
    notifyUnlockListeners();
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

export function isVoiceEnabled(): boolean {
  return voiceEnabled;
}

export function setVoiceEnabled(enabled: boolean): void {
  voiceEnabled = enabled;
  persistVoiceEnabled(enabled);
  if (!enabled) {
    muteVoice();
  }
}

/** Stop current clip and clear the pending speech queue. */
export function muteVoice(): void {
  speechQueue = [];
  if (currentSpeechEl) {
    currentSpeechEl.pause();
    currentSpeechEl.src = "";
    currentSpeechEl = null;
  }
  speechPlaying = false;
  restoreSoundtrackAfterSpeech();
}

function duckSoundtrackForSpeech(): void {
  const track = soundtrackEl;
  if (!track || track.paused) {
    return;
  }
  soundtrackPausedForSpeech = true;
  track.pause();
}

function restoreSoundtrackAfterSpeech(): void {
  if (!soundtrackPausedForSpeech) {
    return;
  }
  soundtrackPausedForSpeech = false;
  if (!unlocked || !soundtrackEl) {
    return;
  }
  soundtrackEl.volume = SOUNDTRACK_VOLUME;
  void soundtrackEl.play().catch(() => {
    // autoplay blocked — ignore
  });
}

/** Play one Polly clip; ducks the tavern loop for the duration. */
export async function playSpeechFromUrl(url: string): Promise<void> {
  if (!isAudioUnlocked() || !voiceEnabled) {
    return;
  }

  return new Promise((resolve) => {
    const el = new Audio(url);
    currentSpeechEl = el;

    const finish = () => {
      if (currentSpeechEl === el) {
        currentSpeechEl = null;
      }
      resolve();
    };

    el.addEventListener("ended", finish, { once: true });
    el.addEventListener("error", finish, { once: true });
    void el.play().catch(finish);
  });
}

async function drainSpeechQueue(): Promise<void> {
  if (speechPlaying || !voiceEnabled || !isAudioUnlocked()) {
    return;
  }

  speechPlaying = true;
  duckSoundtrackForSpeech();

  while (speechQueue.length > 0 && voiceEnabled && isAudioUnlocked()) {
    const url = speechQueue.shift();
    if (!url) {
      continue;
    }
    try {
      await playSpeechFromUrl(url);
    } catch {
      // silent — keep queue moving
    }
  }

  speechPlaying = false;
  restoreSoundtrackAfterSpeech();

  if (speechQueue.length > 0 && voiceEnabled && isAudioUnlocked()) {
    void drainSpeechQueue();
  }
}

/** Enqueue a presigned MP3 URL for sequential playback. */
export function queueSpeechFromUrl(url: string): void {
  if (!isAudioUnlocked() || !voiceEnabled) {
    return;
  }
  speechQueue.push(url);
  void drainSpeechQueue();
}

export function stopAmbience(): void {
  if (!soundtrackEl) {
    return;
  }
  soundtrackEl.pause();
  soundtrackEl.currentTime = 0;
}

export function disposeAudio(): void {
  muteVoice();
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
  unlockListeners.clear();
}

export function isAudioUnlocked(): boolean {
  return unlocked;
}

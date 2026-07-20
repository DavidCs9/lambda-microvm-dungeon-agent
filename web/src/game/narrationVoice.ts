import {
  isAudioUnlocked,
  isVoiceEnabled,
  muteVoice,
  onAudioUnlock,
  queueSpeechFromUrl,
  setVoiceEnabled,
} from "./audio";
import { appendDelta, flushRemainder } from "./sentenceSplitter";
import type { ApiClient } from "../net/api";
import type { LanguageCode } from "../net/types";
import { getGameState, type GameState } from "../state/store";

let api: ApiClient | null = null;
let speechLive = false;
let spokenOpeningKey: string | null = null;
let turnBuffer = "";
let spokenThisTurn = "";
let currentLanguage: LanguageCode = "es";

/** Serialize /speech fetches so URLs enqueue in narration order. */
let fetchChain: Promise<void> = Promise.resolve();

export function setSpeechLive(live: boolean): void {
  speechLive = live;
  turnBuffer = "";
  spokenThisTurn = "";
  if (!live) {
    muteVoice();
    // Drop in-flight enqueue work; new requests check voice/unlocked.
    fetchChain = Promise.resolve();
  }
}

export function isSpeechLive(): boolean {
  return speechLive;
}

export function toggleVoice(): boolean {
  const next = !isVoiceEnabled();
  setVoiceEnabled(next);
  if (!next) {
    onMute();
  }
  return next;
}

export function onMute(): void {
  turnBuffer = "";
  spokenThisTurn = "";
  muteVoice();
  fetchChain = Promise.resolve();
}

export function onTurnStarted(): void {
  turnBuffer = "";
  spokenThisTurn = "";
}

export function onNarrationDelta(text: string): void {
  if (!speechLive) {
    return;
  }
  syncLanguage();
  const { sentences, rest, emitted } = appendDelta(turnBuffer, text);
  turnBuffer = rest;
  spokenThisTurn += emitted;
  for (const sentence of sentences) {
    enqueueSpeechInOrder(sentence);
  }
}

export function onTurnCompleted(finalNarration: string): void {
  if (!speechLive) {
    turnBuffer = "";
    spokenThisTurn = "";
    return;
  }

  syncLanguage();

  const remainderRaw = turnBuffer;
  const remainder = flushRemainder(turnBuffer);
  if (remainder) {
    spokenThisTurn += remainderRaw;
    enqueueSpeechInOrder(remainder);
  }

  const finalText = finalNarration;
  if (finalText.trim()) {
    if (!spokenThisTurn.trim()) {
      enqueueSpeechInOrder(finalText.trim());
    } else if (
      finalText.startsWith(spokenThisTurn) &&
      finalText.length > spokenThisTurn.length
    ) {
      const tail = finalText.slice(spokenThisTurn.length).trim();
      if (tail) {
        enqueueSpeechInOrder(tail);
      }
    }
  }

  turnBuffer = "";
  spokenThisTurn = "";
}

function syncLanguage(): void {
  const state = getGameState();
  currentLanguage = resolveLanguage(state);
}

function resolveLanguage(state: GameState): LanguageCode {
  return state.session?.language ?? state.opening?.language ?? "es";
}

function openingKey(state: GameState): string | null {
  if (!state.opening) {
    return null;
  }
  const campaignId = state.campaign?.campaignId ?? "";
  return `${campaignId}:${state.opening.title}`;
}

function maybeSpeakOpening(state: GameState): void {
  // Opening speech is for Nueva partida / forge — Continuar uses screen "play".
  if (state.screen !== "opening" || !state.opening) {
    return;
  }
  if (!isVoiceEnabled() || !isAudioUnlocked()) {
    return;
  }

  const key = openingKey(state);
  if (!key || key === spokenOpeningKey) {
    return;
  }
  spokenOpeningKey = key;

  const language = resolveLanguage(state);
  const blocks = [...state.opening.blocks]
    .filter((block) => block.narratable)
    .sort((a, b) => a.position - b.position);

  for (const block of blocks) {
    const text = block.text.trim();
    if (text) {
      enqueueSpeechInOrder(text, language);
    }
  }
}

function enqueueSpeechInOrder(
  text: string,
  language: LanguageCode = currentLanguage,
): void {
  fetchChain = fetchChain.then(() => requestAndQueueSpeech(text, language));
}

async function requestAndQueueSpeech(
  text: string,
  language: LanguageCode = currentLanguage,
): Promise<void> {
  if (!api || !isVoiceEnabled() || !isAudioUnlocked()) {
    return;
  }
  try {
    const envelope = await api.postSpeech(text, language);
    if (!isVoiceEnabled() || !isAudioUnlocked()) {
      return;
    }
    queueSpeechFromUrl(envelope.url);
  } catch {
    // silent — gameplay continues
  }
}

export function resetOpeningSpeechMemory(): void {
  spokenOpeningKey = null;
}

export function initNarrationVoice(
  client: ApiClient,
  onStoreChange: (listener: () => void) => () => void,
): void {
  api = client;

  onAudioUnlock(() => {
    maybeSpeakOpening(getGameState());
  });

  let prev = getGameState();
  onStoreChange(() => {
    const next = getGameState();
    if (
      next.screen === "opening" &&
      (next.opening !== prev.opening || next.screen !== prev.screen)
    ) {
      maybeSpeakOpening(next);
    }
    if (next.screen === "menu" && prev.screen !== "menu") {
      resetOpeningSpeechMemory();
      muteVoice();
      fetchChain = Promise.resolve();
    }
    prev = next;
  });
}

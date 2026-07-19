import { useSyncExternalStore } from "react";
import { ApiClient, ApiError } from "../net/api";
import type {
  CampaignRecord,
  ControlPlaneEvent,
  OpeningBlock,
  OpeningBlockKind,
  OpeningDocument,
  SessionRecord,
} from "../net/types";
import { RealtimeClient, type WsStatus } from "../net/ws";

const PLAYER_KEY = "dungeon-agent.playerId";
const DICE_CLEAR_MS = 1400;

export type Screen = "landing" | "ritual" | "phase" | "opening" | "play" | "outcome";

export type DiceBeat = {
  roll: number;
  difficulty: number;
  success: boolean;
  turnId: string;
} | null;

export interface GameState {
  screen: Screen;
  playerId: string;
  wsStatus: WsStatus;
  campaign: CampaignRecord | null;
  session: SessionRecord | null;
  opening: OpeningDocument | null;
  expectedRevision: number;
  phaseLabel: string | null;
  phaseKind: "campaign" | "session" | null;
  turnPending: boolean;
  narrationStream: string;
  turnLog: Array<{ turnId: string; narration: string; success?: boolean; roll?: number }>;
  diceBeat: DiceBeat;
  outcome: "won" | "lost" | "abandoned" | null;
  errorMessage: string | null;
}

type Listener = () => void;

const listeners = new Set<Listener>();
let diceClearTimer: number | null = null;

function loadPlayerId(): string {
  try {
    return localStorage.getItem(PLAYER_KEY) ?? "lab_player_1";
  } catch {
    return "lab_player_1";
  }
}

function persistPlayerId(playerId: string): void {
  try {
    localStorage.setItem(PLAYER_KEY, playerId);
  } catch {
    // ignore quota / private mode
  }
}

const httpUrl = (import.meta.env.VITE_HTTP_URL ?? "").replace(/\/$/, "");
const wsUrl = (import.meta.env.VITE_WS_URL ?? "").replace(/\/$/, "");

function createInitialState(playerId: string): GameState {
  return {
    screen: "landing",
    playerId,
    wsStatus: "disconnected",
    campaign: null,
    session: null,
    opening: null,
    expectedRevision: 0,
    phaseLabel: null,
    phaseKind: null,
    turnPending: false,
    narrationStream: "",
    turnLog: [],
    diceBeat: null,
    outcome: null,
    errorMessage: null,
  };
}

let state: GameState = createInitialState(loadPlayerId());

function emit(): void {
  for (const listener of listeners) {
    listener();
  }
}

function setState(patch: Partial<GameState> | ((prev: GameState) => GameState)): void {
  state = typeof patch === "function" ? patch(state) : { ...state, ...patch };
  emit();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getGameState(): GameState {
  return state;
}

export function useGameStore<T>(selector: (s: GameState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => selector(state),
    () => selector(state),
  );
}

function errorMessageOf(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function ensureConfigured(): void {
  if (!httpUrl || !wsUrl) {
    throw new Error(
      "Missing VITE_HTTP_URL / VITE_WS_URL. Copy web/.env.example to web/.env.local.",
    );
  }
}

function clearDiceTimer(): void {
  if (diceClearTimer !== null) {
    window.clearTimeout(diceClearTimer);
    diceClearTimer = null;
  }
}

function scheduleDiceClear(): void {
  clearDiceTimer();
  diceClearTimer = window.setTimeout(() => {
    diceClearTimer = null;
    setState({ diceBeat: null });
  }, DICE_CLEAR_MS);
}

function payloadTurnId(payload: Record<string, unknown> | undefined): string {
  if (!payload) {
    return "";
  }
  const raw = payload.turnId ?? payload.turn_id;
  return typeof raw === "string" ? raw : "";
}

const OPENING_KINDS = new Set<OpeningBlockKind>([
  "identity",
  "background",
  "motivation",
  "knowledge",
  "situation",
  "possible_action",
]);

function parseOpening(value: unknown): OpeningDocument | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const rec = value as Record<string, unknown>;
  const schemaVersion = rec.schemaVersion ?? rec.schema_version;
  if (schemaVersion !== 1 || typeof rec.title !== "string" || !Array.isArray(rec.blocks)) {
    return null;
  }
  const language = rec.language === "en" ? "en" : "es";
  const blocks: OpeningBlock[] = [];
  for (const item of rec.blocks) {
    if (typeof item !== "object" || item === null) {
      continue;
    }
    const block = item as Record<string, unknown>;
    if (
      typeof block.id !== "string" ||
      typeof block.position !== "number" ||
      typeof block.kind !== "string" ||
      typeof block.text !== "string"
    ) {
      continue;
    }
    if (!OPENING_KINDS.has(block.kind as OpeningBlockKind)) {
      continue;
    }
    blocks.push({
      id: block.id,
      position: block.position,
      kind: block.kind as OpeningBlockKind,
      text: block.text,
      narratable: block.narratable !== false,
    });
  }
  if (blocks.length === 0) {
    return null;
  }
  return { schemaVersion: 1, language, title: rec.title, blocks };
}

function applyEvent(event: ControlPlaneEvent): void {
  const campaign = state.campaign;
  const session = state.session;

  if (event.campaignId && campaign && event.campaignId !== campaign.campaignId) {
    return;
  }
  if (event.sessionId && session && event.sessionId !== session.sessionId) {
    return;
  }

  const payload = event.payload ?? {};

  switch (event.type) {
    case "campaign.creation.started": {
      if (!campaign) {
        return;
      }
      setState({
        campaign: {
          ...campaign,
          status: "creating",
          lastEventSequence: Math.max(campaign.lastEventSequence, event.sequence),
        },
        errorMessage: null,
      });
      return;
    }
    case "campaign.phase.changed": {
      if (!campaign) {
        return;
      }
      const phase = typeof payload.phase === "string" ? payload.phase : campaign.phase;
      setState({
        campaign: {
          ...campaign,
          phase,
          lastEventSequence: Math.max(campaign.lastEventSequence, event.sequence),
        },
        phaseLabel: phase,
        phaseKind: "campaign",
      });
      return;
    }
    case "campaign.ready": {
      if (!campaign) {
        return;
      }
      const revision =
        typeof payload.revision === "number" ? payload.revision : campaign.revision;
      const opening = parseOpening(payload.opening) ?? state.opening;
      setState({
        campaign: {
          ...campaign,
          status: "ready",
          phase: "ready",
          revision,
          lastEventSequence: Math.max(campaign.lastEventSequence, event.sequence),
        },
        opening,
        phaseLabel: null,
        phaseKind: null,
        screen: "opening",
        errorMessage: null,
      });
      return;
    }
    case "campaign.creation.failed": {
      if (!campaign) {
        return;
      }
      const code = typeof payload.code === "string" ? payload.code : "campaign_creation_failed";
      setState({
        campaign: {
          ...campaign,
          status: "failed",
          phase: "failed",
          lastEventSequence: Math.max(campaign.lastEventSequence, event.sequence),
        },
        errorMessage: code,
        screen: state.screen === "phase" ? "phase" : "ritual",
      });
      return;
    }
    case "session.creation.started": {
      if (!session) {
        return;
      }
      setState({
        session: {
          ...session,
          status: "creating",
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        errorMessage: null,
      });
      return;
    }
    case "session.phase.changed": {
      if (!session) {
        return;
      }
      const phase = typeof payload.phase === "string" ? payload.phase : session.phase;
      setState({
        session: {
          ...session,
          phase,
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        phaseLabel: phase,
        phaseKind: "session",
      });
      return;
    }
    case "session.ready": {
      if (!session) {
        return;
      }
      const revision =
        typeof payload.revision === "number" ? payload.revision : session.revision;
      const opening = parseOpening(payload.opening) ?? state.opening;
      setState({
        session: {
          ...session,
          status: "ready",
          phase: "ready",
          revision,
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        opening,
        expectedRevision: revision,
        phaseLabel: null,
        phaseKind: null,
        screen: "play",
        errorMessage: null,
      });
      return;
    }
    case "session.creation.failed": {
      const code = typeof payload.code === "string" ? payload.code : "session_creation_failed";
      setState({
        session: session
          ? {
              ...session,
              status: "failed",
              phase: "failed",
              lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
            }
          : null,
        errorMessage: code,
        phaseLabel: null,
        phaseKind: null,
        screen: "opening",
      });
      return;
    }
    case "turn.started": {
      if (!session) {
        return;
      }
      setState({
        session: {
          ...session,
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        turnPending: true,
        narrationStream: "",
        errorMessage: null,
      });
      return;
    }
    case "dice.rolled": {
      if (!session) {
        return;
      }
      const turnId = payloadTurnId(payload);
      const roll = typeof payload.roll === "number" ? payload.roll : 0;
      const difficulty = typeof payload.difficulty === "number" ? payload.difficulty : 0;
      const success = payload.success === true;
      clearDiceTimer();
      setState({
        session: {
          ...session,
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        diceBeat: { turnId, roll, difficulty, success },
      });
      return;
    }
    case "narration.delta": {
      if (!session) {
        return;
      }
      const text = typeof payload.text === "string" ? payload.text : "";
      setState({
        session: {
          ...session,
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        narrationStream: state.narrationStream + text,
      });
      return;
    }
    case "turn.completed": {
      if (!session) {
        return;
      }
      const turnId = payloadTurnId(payload);
      const narration =
        typeof payload.narration === "string" ? payload.narration : state.narrationStream;
      const revision =
        typeof payload.revision === "number" ? payload.revision : state.expectedRevision;
      const dice = state.diceBeat;
      const entry = {
        turnId,
        narration,
        ...(dice && dice.turnId === turnId
          ? { success: dice.success, roll: dice.roll }
          : {}),
      };
      setState({
        session: {
          ...session,
          revision,
          status: "active",
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        expectedRevision: revision,
        turnPending: false,
        narrationStream: narration,
        turnLog: [...state.turnLog, entry],
      });
      scheduleDiceClear();
      return;
    }
    case "session.completed": {
      if (!session) {
        return;
      }
      const outcomeRaw = payload.outcome;
      const outcome =
        outcomeRaw === "won" || outcomeRaw === "lost" || outcomeRaw === "abandoned"
          ? outcomeRaw
          : "abandoned";
      const revision =
        typeof payload.revision === "number" ? payload.revision : session.revision;
      setState({
        session: {
          ...session,
          status: "completed",
          revision,
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        expectedRevision: revision,
        outcome,
        turnPending: false,
        screen: "outcome",
      });
      return;
    }
    default:
      // Soft-ignore unknown events; still advance sequence when scoped.
      if (campaign && event.campaignId === campaign.campaignId && !event.sessionId) {
        setState({
          campaign: {
            ...campaign,
            lastEventSequence: Math.max(campaign.lastEventSequence, event.sequence),
          },
        });
      } else if (session && event.sessionId === session.sessionId) {
        setState({
          session: {
            ...session,
            lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
          },
        });
      }
  }
}

const api = new ApiClient({ baseUrl: httpUrl, playerId: state.playerId });
const realtime = new RealtimeClient({
  wsUrl,
  playerId: state.playerId,
  onEvent: applyEvent,
  onStatus: (status) => {
    setState({ wsStatus: status });
  },
});

function syncClients(playerId: string): void {
  api.setPlayerId(playerId);
  realtime.setPlayerId(playerId);
}

export const gameActions = {
  setPlayerId(id: string): void {
    const playerId = id.trim();
    persistPlayerId(playerId);
    syncClients(playerId);
    setState({ playerId });
  },

  beginRitual(): void {
    syncClients(state.playerId);
    persistPlayerId(state.playerId);
    if (wsUrl) {
      realtime.connect();
    }
    setState({
      screen: "ritual",
      errorMessage: null,
      outcome: null,
    });
  },

  async createCampaign(): Promise<void> {
    syncClients(state.playerId);
    try {
      ensureConfigured();
      if (!realtime.connected) {
        realtime.connect();
      }
      setState({
        screen: "phase",
        phaseKind: "campaign",
        phaseLabel: "requested",
        errorMessage: null,
        session: null,
        opening: null,
        turnLog: [],
        narrationStream: "",
        turnPending: false,
        diceBeat: null,
        outcome: null,
        expectedRevision: 0,
      });
      const envelope = await api.createCampaign("es");
      const campaign = envelope.campaign;
      setState({
        campaign,
        phaseLabel: campaign.phase,
        phaseKind: "campaign",
      });
      realtime.subscribeCampaign(campaign.campaignId, campaign.lastEventSequence);
    } catch (error) {
      setState({
        errorMessage: errorMessageOf(error),
        screen: "ritual",
        phaseLabel: null,
        phaseKind: null,
      });
    }
  },

  async startSession(): Promise<void> {
    const campaign = state.campaign;
    if (!campaign || campaign.status !== "ready") {
      setState({ errorMessage: "Campaign must be ready before starting a session" });
      return;
    }
    syncClients(state.playerId);
    try {
      ensureConfigured();
      if (!realtime.connected) {
        realtime.connect();
      }
      setState({
        screen: "phase",
        phaseKind: "session",
        phaseLabel: "requested",
        errorMessage: null,
        turnLog: [],
        narrationStream: "",
        turnPending: false,
        diceBeat: null,
        outcome: null,
      });
      const envelope = await api.createSession(campaign.campaignId, "es");
      const session = envelope.session;
      setState({
        session,
        expectedRevision: session.revision,
        phaseLabel: session.phase,
        phaseKind: "session",
      });
      realtime.subscribeSession(session.sessionId, session.lastEventSequence);
    } catch (error) {
      setState({
        errorMessage: errorMessageOf(error),
        screen: "opening",
        phaseLabel: null,
        phaseKind: null,
      });
    }
  },

  async submitAction(action: string): Promise<void> {
    const session = state.session;
    const trimmed = action.trim();
    if (!session || !trimmed) {
      return;
    }
    syncClients(state.playerId);
    try {
      ensureConfigured();
      await api.submitAction(session.sessionId, trimmed, state.expectedRevision);
      setState({ errorMessage: null });
    } catch (error) {
      setState({ errorMessage: errorMessageOf(error) });
    }
  },

  continueFromOpening(): void {
    const session = state.session;
    if (session && (session.status === "ready" || session.status === "active")) {
      setState({ screen: "play", errorMessage: null });
      return;
    }
    void gameActions.startSession();
  },

  dismissDiceBeat(): void {
    clearDiceTimer();
    setState({ diceBeat: null });
  },

  resetToLanding(): void {
    clearDiceTimer();
    setState({
      ...createInitialState(state.playerId),
      wsStatus: state.wsStatus,
    });
  },
};

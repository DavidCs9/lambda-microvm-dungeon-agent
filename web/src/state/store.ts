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
import { humanError } from "../ui/copy";

const PLAYER_KEY = "dungeon-agent.playerId";
export const PLAYER_LANGUAGE = "es" as const;

export type Screen = "menu" | "campaigns" | "phase" | "opening" | "play" | "outcome";

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
  campaigns: CampaignRecord[];
  campaignsLoading: boolean;
  activeSessions: SessionRecord[];
  activeSessionsLoading: boolean;
  session: SessionRecord | null;
  opening: OpeningDocument | null;
  expectedRevision: number;
  phaseLabel: string | null;
  phaseKind: "campaign" | "session" | null;
  turnPending: boolean;
  narrationStream: string;
  turnLog: Array<{
    turnId: string;
    narration: string;
    success?: boolean;
    roll?: number;
    action?: string;
  }>;
  diceBeat: DiceBeat;
  outcome: "won" | "lost" | "abandoned" | null;
  errorMessage: string | null;
}

type Listener = () => void;

const listeners = new Set<Listener>();
let pendingActionText = "";

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
    screen: "menu",
    playerId,
    wsStatus: "disconnected",
    campaign: null,
    campaigns: [],
    campaignsLoading: false,
    activeSessions: [],
    activeSessionsLoading: false,
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

function errorCodeOf(error: unknown): string | null {
  if (error instanceof ApiError) {
    const body = error.body;
    if (typeof body === "object" && body !== null && "error" in body) {
      const code = (body as { error?: { code?: unknown } }).error?.code;
      if (typeof code === "string") {
        return code;
      }
    }
  }
  return null;
}

function errorMessageOf(error: unknown): string {
  const code = errorCodeOf(error);
  if (code) {
    console.warn(`API error code: ${code}`);
    return humanError(code);
  }
  if (error instanceof Error) {
    console.warn(`API error: ${error.message}`);
  }
  return humanError(null);
}

function ensureConfigured(): void {
  if (!httpUrl || !wsUrl) {
    throw new Error(
      "Missing VITE_HTTP_URL / VITE_WS_URL. Copy web/.env.example to web/.env.local.",
    );
  }
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
      console.warn(`campaign.creation.failed: ${code}`);
      setState({
        campaign: {
          ...campaign,
          status: "failed",
          phase: "failed",
          lastEventSequence: Math.max(campaign.lastEventSequence, event.sequence),
        },
        errorMessage: humanError(code),
        screen: state.screen === "phase" ? "phase" : "campaigns",
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
      const awaitingAction = phase === "ready";
      setState({
        session: {
          ...session,
          phase,
          status: awaitingAction ? "ready" : session.status,
          lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        },
        phaseLabel: phase,
        phaseKind: "session",
        ...(awaitingAction ? { turnPending: false } : {}),
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
      console.warn(`session.creation.failed: ${code}`);
      setState({
        session: session
          ? {
              ...session,
              status: "failed",
              phase: "failed",
              lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
            }
          : null,
        errorMessage: humanError(code),
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
        diceBeat: null,
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
        ...(pendingActionText ? { action: pendingActionText } : {}),
      };
      pendingActionText = "";
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

  goToCampaigns(): void {
    syncClients(state.playerId);
    persistPlayerId(state.playerId);
    if (wsUrl) {
      realtime.connect();
    }
    setState({
      screen: "campaigns",
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
        campaigns: [],
        session: null,
        opening: null,
        turnLog: [],
        narrationStream: "",
        turnPending: false,
        diceBeat: null,
        outcome: null,
        expectedRevision: 0,
      });
      const envelope = await api.createCampaign(PLAYER_LANGUAGE);
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
        screen: "campaigns",
        phaseLabel: null,
        phaseKind: null,
      });
    }
  },

  async loadCampaigns(): Promise<void> {
    syncClients(state.playerId);
    setState({ campaignsLoading: true, errorMessage: null });
    try {
      ensureConfigured();
      const envelope = await api.listCampaigns("ready");
      setState({
        campaigns: envelope.campaigns,
        campaignsLoading: false,
        screen: "campaigns",
      });
    } catch (error) {
      setState({
        campaignsLoading: false,
        errorMessage: errorMessageOf(error),
        screen: "campaigns",
      });
    }
  },

  async loadActiveSessions(): Promise<void> {
    syncClients(state.playerId);
    setState({ activeSessionsLoading: true, errorMessage: null });
    try {
      ensureConfigured();
      const [sessionsEnvelope, campaignsEnvelope] = await Promise.all([
        api.listActiveSessions(),
        api.listCampaigns(),
      ]);
      setState({
        activeSessions: sessionsEnvelope.sessions,
        campaigns: campaignsEnvelope.campaigns,
        activeSessionsLoading: false,
      });
    } catch (error) {
      setState({
        activeSessionsLoading: false,
        errorMessage: errorMessageOf(error),
      });
    }
  },

  async resumeCampaign(campaignId: string): Promise<void> {
    syncClients(state.playerId);
    try {
      ensureConfigured();
      if (!realtime.connected) {
        realtime.connect();
      }
      setState({ errorMessage: null });
      const [campaignEnvelope, openingEnvelope] = await Promise.all([
        api.getCampaign(campaignId),
        api.getCampaignOpening(campaignId),
      ]);
      const campaign = campaignEnvelope.campaign;
      const opening = parseOpening(openingEnvelope.opening);
      if (!opening) {
        throw new Error("La apertura de la campaña no es válida.");
      }
      setState({
        campaign,
        opening,
        screen: "opening",
        phaseLabel: null,
        phaseKind: null,
        session: null,
        turnLog: [],
        narrationStream: "",
        turnPending: false,
        diceBeat: null,
        outcome: null,
        expectedRevision: 0,
        errorMessage: null,
      });
      realtime.subscribeCampaign(campaign.campaignId, campaign.lastEventSequence);
    } catch (error) {
      setState({
        errorMessage: errorMessageOf(error),
        screen: "campaigns",
      });
    }
  },

  async startSession(): Promise<void> {
    const campaign = state.campaign;
    if (!campaign || campaign.status !== "ready") {
      setState({ errorMessage: humanError("validation_failed") });
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
      const envelope = await api.createSession(campaign.campaignId, PLAYER_LANGUAGE);
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
    pendingActionText = trimmed;
    setState({ turnPending: true, narrationStream: "", errorMessage: null });
    try {
      ensureConfigured();
      await api.submitAction(session.sessionId, trimmed, state.expectedRevision);
    } catch (error) {
      pendingActionText = "";
      setState({
        turnPending: false,
        errorMessage: errorMessageOf(error),
      });
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

  async resumeSession(sessionId: string): Promise<void> {
    syncClients(state.playerId);
    try {
      ensureConfigured();
      if (!realtime.connected) {
        realtime.connect();
      }
      setState({ errorMessage: null });

      const sessionEnvelope = await api.getSession(sessionId);
      const session = sessionEnvelope.session;

      if (session.status === "completed" || session.status === "failed") {
        setState({ errorMessage: humanError("session_not_found") });
        void gameActions.loadActiveSessions();
        return;
      }

      let campaign: CampaignRecord | null = null;
      let opening: OpeningDocument | null = null;
      if (session.campaignId) {
        try {
          const campaignEnvelope = await api.getCampaign(session.campaignId);
          campaign = campaignEnvelope.campaign;
          if (campaign.status === "ready") {
            const openingEnvelope = await api.getCampaignOpening(session.campaignId);
            opening = parseOpening(openingEnvelope.opening);
          }
        } catch (error) {
          console.warn("resumeSession: campaign/opening fetch failed", error);
          campaign = null;
          opening = null;
        }
      }

      const turnLog: GameState["turnLog"] = [];
      if (session.revision > 0) {
        const eventsEnvelope = await api.getSessionEvents(sessionId, 0);
        const diceByTurn = new Map<string, { roll: number; success: boolean }>();
        for (const event of eventsEnvelope.events) {
          if (event.type !== "dice.rolled") {
            continue;
          }
          const payload = event.payload ?? {};
          const turnId = payloadTurnId(payload);
          if (!turnId) {
            continue;
          }
          diceByTurn.set(turnId, {
            roll: typeof payload.roll === "number" ? payload.roll : 0,
            success: payload.success === true,
          });
        }
        for (const event of eventsEnvelope.events) {
          if (event.type !== "turn.completed") {
            continue;
          }
          const payload = event.payload ?? {};
          const turnId = payloadTurnId(payload);
          const narration = typeof payload.narration === "string" ? payload.narration : "";
          const dice = diceByTurn.get(turnId);
          turnLog.push({
            turnId,
            narration,
            ...(dice ? { success: dice.success, roll: dice.roll } : {}),
          });
        }
      }

      setState({
        session,
        campaign,
        opening,
        expectedRevision: session.revision,
        turnLog,
        narrationStream: "",
        turnPending: false,
        diceBeat: null,
        outcome: null,
        phaseLabel: null,
        phaseKind: null,
        screen: "play",
        errorMessage: null,
      });
      realtime.subscribeSession(session.sessionId, session.lastEventSequence);
    } catch (error) {
      setState({ errorMessage: errorMessageOf(error) });
      void gameActions.loadActiveSessions();
    }
  },

  async abandonSession(sessionId: string): Promise<void> {
    syncClients(state.playerId);
    const idempotencyKey = crypto.randomUUID();
    try {
      ensureConfigured();
      try {
        await api.abandonSession(sessionId, idempotencyKey);
      } catch (firstError) {
        console.warn("abandonSession: first attempt failed, retrying once", firstError);
        await api.abandonSession(sessionId, idempotencyKey);
      }
    } catch (error) {
      console.warn("abandonSession: retry also failed, dropping locally", error);
    }
    setState((prev) => ({
      ...prev,
      activeSessions: prev.activeSessions.filter((s) => s.sessionId !== sessionId),
    }));
  },

  resetToMenu(): void {
    setState({
      ...createInitialState(state.playerId),
      wsStatus: state.wsStatus,
    });
  },
};

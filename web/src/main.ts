import { ApiClient, ApiError } from "./api";
import type { CampaignRecord, ControlPlaneEvent, SessionRecord } from "./types";
import { RealtimeClient, type WsStatus } from "./ws";

const PLAYER_KEY = "dungeon-agent.playerId";

const httpUrl = (import.meta.env.VITE_HTTP_URL ?? "").replace(/\/$/, "");
const wsUrl = (import.meta.env.VITE_WS_URL ?? "").replace(/\/$/, "");

const playerInput = el<HTMLInputElement>("player-id");
const httpUrlEl = el("http-url");
const wsUrlEl = el("ws-url");
const connectBtn = el<HTMLButtonElement>("connect-ws");
const wsStatusEl = el("ws-status");
const createCampaignBtn = el<HTMLButtonElement>("create-campaign");
const refreshCampaignBtn = el<HTMLButtonElement>("refresh-campaign");
const campaignMetaEl = el("campaign-meta");
const createSessionBtn = el<HTMLButtonElement>("create-session");
const refreshSessionBtn = el<HTMLButtonElement>("refresh-session");
const sessionMetaEl = el("session-meta");
const actionText = el<HTMLTextAreaElement>("action-text");
const submitActionBtn = el<HTMLButtonElement>("submit-action");
const eventList = el("event-list");
const lastEventEl = el("last-event");

httpUrlEl.textContent = httpUrl || "(set VITE_HTTP_URL in web/.env.local)";
wsUrlEl.textContent = wsUrl || "(set VITE_WS_URL in web/.env.local)";

playerInput.value = localStorage.getItem(PLAYER_KEY) ?? "lab_player_1";

let campaign: CampaignRecord | null = null;
let session: SessionRecord | null = null;
let expectedRevision = 0;

const api = new ApiClient({ baseUrl: httpUrl, playerId: playerInput.value.trim() });
const realtime = new RealtimeClient({
  wsUrl,
  playerId: playerInput.value.trim(),
  onEvent: handleEvent,
  onStatus: setWsStatus,
  onMessage: (raw) => {
    if (typeof raw === "object" && raw !== null && "type" in raw && (raw as { type: string }).type === "pong") {
      return;
    }
  },
});

playerInput.addEventListener("change", syncPlayer);
playerInput.addEventListener("blur", syncPlayer);
connectBtn.addEventListener("click", () => {
  syncPlayer();
  realtime.connect();
});
createCampaignBtn.addEventListener("click", () => void onCreateCampaign());
refreshCampaignBtn.addEventListener("click", () => void onRefreshCampaign());
createSessionBtn.addEventListener("click", () => void onCreateSession());
refreshSessionBtn.addEventListener("click", () => void onRefreshSession());
submitActionBtn.addEventListener("click", () => void onSubmitAction());

renderCampaign();
renderSession();

function syncPlayer(): void {
  const playerId = playerInput.value.trim();
  localStorage.setItem(PLAYER_KEY, playerId);
  api.setPlayerId(playerId);
  realtime.setPlayerId(playerId);
}

function setWsStatus(status: WsStatus, detail?: string): void {
  wsStatusEl.className = `status ${status === "connected" ? "connected" : status === "error" ? "error" : ""}`;
  const labels: Record<WsStatus, string> = {
    disconnected: "desconectado",
    connecting: "conectando",
    connected: "conectado",
    error: "error",
  };
  const label = labels[status];
  wsStatusEl.textContent = detail ? `${label}: ${detail}` : label;
}

function handleEvent(event: ControlPlaneEvent): void {
  appendEvent(event);
  lastEventEl.textContent = JSON.stringify(event, null, 2);

  if (event.type.startsWith("campaign.")) {
    if (campaign && event.campaignId && event.campaignId !== campaign.campaignId) {
      return;
    }
    const phase = typeof event.payload?.phase === "string" ? event.payload.phase : undefined;
    if (campaign) {
      campaign = {
        ...campaign,
        lastEventSequence: Math.max(campaign.lastEventSequence, event.sequence),
        phase: phase ?? campaign.phase,
        status:
          event.type === "campaign.ready"
            ? "ready"
            : event.type === "campaign.creation.failed"
              ? "failed"
              : campaign.status,
      };
      if (event.type === "campaign.ready" && typeof event.payload?.revision === "number") {
        campaign = { ...campaign, revision: event.payload.revision };
      }
      renderCampaign();
    }
  }

  if (event.type.startsWith("session.") || event.type.startsWith("turn.") || event.type === "dice.rolled" || event.type === "narration.delta") {
    if (session && event.sessionId && event.sessionId !== session.sessionId) {
      return;
    }
    const phase = typeof event.payload?.phase === "string" ? event.payload.phase : undefined;
    if (session) {
      session = {
        ...session,
        lastEventSequence: Math.max(session.lastEventSequence, event.sequence),
        phase: phase ?? session.phase,
        status:
          event.type === "session.ready"
            ? "ready"
            : event.type === "session.creation.failed"
              ? "failed"
              : event.type === "session.completed"
                ? "completed"
                : session.status,
      };
      if (typeof event.payload?.revision === "number") {
        expectedRevision = event.payload.revision;
        session = { ...session, revision: event.payload.revision };
      }
      renderSession();
    }
  }
}

async function onCreateCampaign(): Promise<void> {
  syncPlayer();
  ensureConfigured();
  createCampaignBtn.disabled = true;
  try {
    if (!realtime.connected) {
      realtime.connect();
    }
    const envelope = await api.createCampaign("es");
    campaign = envelope.campaign;
    session = null;
    expectedRevision = 0;
    renderCampaign();
    renderSession();
    realtime.subscribeCampaign(campaign.campaignId, campaign.lastEventSequence);
    logNote(`campaña creada: ${campaign.campaignId} (${campaign.status}/${campaign.phase})`);
  } catch (error) {
    logError(error);
  } finally {
    createCampaignBtn.disabled = false;
  }
}

async function onRefreshCampaign(): Promise<void> {
  if (!campaign) {
    return;
  }
  syncPlayer();
  try {
    const envelope = await api.getCampaign(campaign.campaignId);
    campaign = envelope.campaign;
    renderCampaign();
  } catch (error) {
    logError(error);
  }
}

async function onCreateSession(): Promise<void> {
  if (!campaign || campaign.status !== "ready") {
    logNote("la campaña debe estar lista antes de crear una sesión");
    return;
  }
  syncPlayer();
  createSessionBtn.disabled = true;
  try {
    const envelope = await api.createSession(campaign.campaignId, "es");
    session = envelope.session;
    expectedRevision = session.revision;
    renderSession();
    realtime.subscribeSession(session.sessionId, session.lastEventSequence);
    logNote(`sesión creada: ${session.sessionId} (${session.status}/${session.phase})`);
  } catch (error) {
    logError(error);
  } finally {
    renderSession();
  }
}

async function onRefreshSession(): Promise<void> {
  if (!session) {
    return;
  }
  syncPlayer();
  try {
    const envelope = await api.getSession(session.sessionId);
    session = envelope.session;
    expectedRevision = session.revision;
    renderSession();
  } catch (error) {
    logError(error);
  }
}

async function onSubmitAction(): Promise<void> {
  if (!session) {
    return;
  }
  const action = actionText.value.trim();
  if (!action) {
    logNote("escribe una acción primero");
    return;
  }
  syncPlayer();
  submitActionBtn.disabled = true;
  try {
    const accepted = await api.submitAction(session.sessionId, action, expectedRevision);
    logNote(`acción ${accepted.status}: ${accepted.turnId}`);
    actionText.value = "";
  } catch (error) {
    logError(error);
  } finally {
    renderSession();
  }
}

function renderCampaign(): void {
  const ready = campaign?.status === "ready";
  refreshCampaignBtn.disabled = !campaign;
  createSessionBtn.disabled = !ready;
  if (!campaign) {
    campaignMetaEl.textContent = "Sin campaña todavía.";
    return;
  }
  campaignMetaEl.textContent = `${campaign.campaignId} — ${campaign.status} / ${campaign.phase} (rev ${campaign.revision})`;
}

function renderSession(): void {
  const ready = session?.status === "ready" || session?.status === "active";
  refreshSessionBtn.disabled = !session;
  actionText.disabled = !ready;
  submitActionBtn.disabled = !ready;
  createSessionBtn.disabled = !(campaign?.status === "ready");
  if (!session) {
    sessionMetaEl.textContent = campaign?.status === "ready"
      ? "Campaña lista. Crea una sesión para jugar."
      : "Esperando una campaña lista.";
    return;
  }
  sessionMetaEl.textContent = `${session.sessionId} — ${session.status} / ${session.phase} (rev ${expectedRevision})`;
}

function appendEvent(event: ControlPlaneEvent): void {
  const item = document.createElement("li");
  const summary = summarize(event);
  item.textContent = `#${event.sequence} ${event.type}${summary ? ` — ${summary}` : ""}`;
  eventList.appendChild(item);
  eventList.scrollTop = eventList.scrollHeight;
}

function summarize(event: ControlPlaneEvent): string {
  const payload = event.payload ?? {};
  if (typeof payload.phase === "string") {
    return payload.phase;
  }
  if (typeof payload.narration === "string") {
    return truncate(payload.narration);
  }
  if (typeof payload.text === "string") {
    return truncate(payload.text);
  }
  if (typeof payload.roll === "number") {
    return `d20=${payload.roll}${payload.success === true ? " ok" : payload.success === false ? " miss" : ""}`;
  }
  if (typeof payload.code === "string") {
    return payload.code;
  }
  return "";
}

function truncate(value: string, max = 80): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}

function logNote(message: string): void {
  const item = document.createElement("li");
  item.textContent = `nota — ${message}`;
  eventList.appendChild(item);
  eventList.scrollTop = eventList.scrollHeight;
}

function logError(error: unknown): void {
  const message =
    error instanceof ApiError
      ? `${error.message} (${error.status})`
      : error instanceof Error
        ? error.message
        : String(error);
  const item = document.createElement("li");
  item.textContent = `error — ${message}`;
  eventList.appendChild(item);
  eventList.scrollTop = eventList.scrollHeight;
  if (error instanceof ApiError) {
    lastEventEl.textContent = JSON.stringify(error.body, null, 2);
  }
  console.error(error);
}

function ensureConfigured(): void {
  if (!httpUrl || !wsUrl) {
    throw new Error(
      "Faltan VITE_HTTP_URL / VITE_WS_URL. Copia web/.env.example a web/.env.local.",
    );
  }
}

function el<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) {
    throw new Error(`missing #${id}`);
  }
  return node as T;
}

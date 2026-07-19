import type { ControlPlaneEvent } from "./types";

export type WsStatus = "disconnected" | "connecting" | "connected" | "error";

export interface RealtimeClientOptions {
  wsUrl: string;
  playerId: string;
  onEvent: (event: ControlPlaneEvent) => void;
  onStatus: (status: WsStatus, detail?: string) => void;
  onMessage?: (raw: unknown) => void;
}

type SubscribeTarget =
  | { kind: "campaign"; id: string; afterSequence: number }
  | { kind: "session"; id: string; afterSequence: number };

export class RealtimeClient {
  private readonly wsUrl: string;
  private playerId: string;
  private readonly onEvent: (event: ControlPlaneEvent) => void;
  private readonly onStatus: (status: WsStatus, detail?: string) => void;
  private readonly onMessage?: (raw: unknown) => void;
  private socket: WebSocket | null = null;
  private pingTimer: number | null = null;
  private didReconnect = false;
  private subscription: SubscribeTarget | null = null;

  constructor(options: RealtimeClientOptions) {
    this.wsUrl = options.wsUrl.replace(/\/$/, "");
    this.playerId = options.playerId;
    this.onEvent = options.onEvent;
    this.onStatus = options.onStatus;
    this.onMessage = options.onMessage;
  }

  setPlayerId(playerId: string): void {
    this.playerId = playerId;
  }

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  connect(): void {
    if (!this.playerId || this.playerId.length < 3) {
      this.onStatus("error", "playerId must be at least 3 characters");
      return;
    }
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    this.onStatus("connecting");
    const url = `${this.wsUrl}?playerId=${encodeURIComponent(this.playerId)}`;
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.didReconnect = false;
      this.onStatus("connected");
      this.startPing();
      if (this.subscription) {
        this.sendSubscribe(this.subscription);
      }
    });

    socket.addEventListener("message", (message) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(message.data)) as unknown;
      } catch {
        return;
      }
      this.onMessage?.(parsed);
      if (isControlPlaneEvent(parsed)) {
        this.onEvent(parsed);
        if (this.subscription) {
          this.subscription = { ...this.subscription, afterSequence: parsed.sequence };
        }
      }
    });

    socket.addEventListener("close", () => {
      this.stopPing();
      this.onStatus("disconnected");
      if (!this.didReconnect) {
        this.didReconnect = true;
        window.setTimeout(() => this.connect(), 750);
      }
    });

    socket.addEventListener("error", () => {
      this.onStatus("error", "WebSocket error");
    });
  }

  subscribeCampaign(campaignId: string, afterSequence = 0): void {
    this.subscription = { kind: "campaign", id: campaignId, afterSequence };
    if (this.connected) {
      this.sendSubscribe(this.subscription);
    } else {
      this.connect();
    }
  }

  subscribeSession(sessionId: string, afterSequence = 0): void {
    this.subscription = { kind: "session", id: sessionId, afterSequence };
    if (this.connected) {
      this.sendSubscribe(this.subscription);
    } else {
      this.connect();
    }
  }

  disconnect(): void {
    this.stopPing();
    this.didReconnect = true;
    this.socket?.close();
    this.socket = null;
    this.onStatus("disconnected");
  }

  private sendSubscribe(target: SubscribeTarget): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    const body: Record<string, unknown> = {
      action: "subscribe",
      playerId: this.playerId,
      afterSequence: target.afterSequence,
    };
    if (target.kind === "campaign") {
      body.campaignId = target.id;
    } else {
      body.sessionId = target.id;
    }
    this.socket.send(JSON.stringify(body));
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = window.setInterval(() => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ action: "ping" }));
      }
    }, 30_000);
  }

  private stopPing(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }
}

function isControlPlaneEvent(value: unknown): value is ControlPlaneEvent {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return typeof record.type === "string" && typeof record.sequence === "number";
}

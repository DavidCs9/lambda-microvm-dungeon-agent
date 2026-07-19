import type {
  CampaignEnvelope,
  CampaignListEnvelope,
  LanguageCode,
  OpeningEnvelope,
  SessionEnvelope,
  TurnAcceptedEnvelope,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  playerId: string;
}

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export class ApiClient {
  private readonly baseUrl: string;
  private playerId: string;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.playerId = options.playerId;
  }

  setPlayerId(playerId: string): void {
    this.playerId = playerId;
  }

  createCampaign(language: LanguageCode = "es"): Promise<CampaignEnvelope> {
    return this.request<CampaignEnvelope>("POST", "/campaigns", {
      body: { language },
      idempotencyKey: newIdempotencyKey(),
    });
  }

  getCampaign(campaignId: string): Promise<CampaignEnvelope> {
    return this.request<CampaignEnvelope>("GET", `/campaigns/${campaignId}`);
  }

  listCampaigns(status?: string): Promise<CampaignListEnvelope> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return this.request<CampaignListEnvelope>("GET", `/campaigns${query}`);
  }

  getCampaignOpening(campaignId: string): Promise<OpeningEnvelope> {
    return this.request<OpeningEnvelope>("GET", `/campaigns/${campaignId}/opening`);
  }

  createSession(campaignId: string, language: LanguageCode = "es"): Promise<SessionEnvelope> {
    return this.request<SessionEnvelope>("POST", "/sessions", {
      body: { language, campaignId },
      idempotencyKey: newIdempotencyKey(),
    });
  }

  getSession(sessionId: string): Promise<SessionEnvelope> {
    return this.request<SessionEnvelope>("GET", `/sessions/${sessionId}`);
  }

  submitAction(
    sessionId: string,
    action: string,
    expectedRevision: number,
  ): Promise<TurnAcceptedEnvelope> {
    return this.request<TurnAcceptedEnvelope>("POST", `/sessions/${sessionId}/actions`, {
      body: { action, expectedRevision },
      idempotencyKey: newIdempotencyKey(),
    });
  }

  private async request<T>(
    method: string,
    path: string,
    options: { body?: unknown; idempotencyKey?: string } = {},
  ): Promise<T> {
    if (!this.playerId || this.playerId.length < 3) {
      throw new Error("playerId must be at least 3 characters");
    }

    const headers: Record<string, string> = {
      "x-player-id": this.playerId,
      accept: "application/json",
    };
    if (options.body !== undefined) {
      headers["content-type"] = "application/json";
    }
    if (options.idempotencyKey) {
      headers["Idempotency-Key"] = options.idempotencyKey;
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });

    const text = await response.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text) as unknown;
      } catch {
        parsed = text;
      }
    }

    if (!response.ok) {
      const message =
        typeof parsed === "object" &&
        parsed !== null &&
        "error" in parsed &&
        typeof (parsed as { error?: { message?: unknown } }).error?.message === "string"
          ? (parsed as { error: { message: string } }).error.message
          : `HTTP ${response.status}`;
      throw new ApiError(response.status, parsed, message);
    }

    return parsed as T;
  }
}

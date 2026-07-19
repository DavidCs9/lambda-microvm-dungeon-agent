/** Minimal camelCase shapes matching the control-plane contracts. */

export type LanguageCode = "en" | "es";

export interface CampaignRecord {
  campaignId: string;
  ownerId: string;
  language: LanguageCode;
  status: string;
  phase: string;
  revision: number;
  lastEventSequence: number;
}

export interface SessionRecord {
  sessionId: string;
  ownerId: string;
  language: LanguageCode;
  status: string;
  phase: string;
  revision: number;
  lastEventSequence: number;
  campaignId?: string | null;
  campaignRevision?: number | null;
}

export interface CampaignEnvelope {
  version: 1;
  campaign: CampaignRecord;
}

export interface SessionEnvelope {
  version: 1;
  session: SessionRecord;
}

export interface TurnAcceptedEnvelope {
  version: 1;
  sessionId: string;
  turnId: string;
  status: "started" | "duplicate";
}

export interface ErrorEnvelope {
  version: 1;
  error: {
    code: string;
    message: string;
    retryable?: boolean;
    correlationId?: string;
  };
}

export interface ControlPlaneEvent {
  version?: number;
  eventId?: string;
  type: string;
  sequence: number;
  campaignId?: string;
  sessionId?: string;
  correlationId?: string;
  occurredAt?: string;
  payload?: Record<string, unknown>;
}

export type ApiOk =
  | CampaignEnvelope
  | SessionEnvelope
  | TurnAcceptedEnvelope
  | ControlPlaneEvent[];

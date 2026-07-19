/** Minimal camelCase shapes matching the control-plane contracts. */

export type LanguageCode = "en" | "es";

export type OpeningBlockKind =
  | "identity"
  | "background"
  | "motivation"
  | "knowledge"
  | "situation"
  | "possible_action";

export interface OpeningBlock {
  id: string;
  position: number;
  kind: OpeningBlockKind;
  text: string;
  narratable: boolean;
}

export interface OpeningDocument {
  schemaVersion: 1;
  language: LanguageCode;
  title: string;
  blocks: OpeningBlock[];
}

export interface CampaignRecord {
  campaignId: string;
  ownerId: string;
  language: LanguageCode;
  status: string;
  phase: string;
  revision: number;
  lastEventSequence: number;
  openingTitle?: string | null;
  createdAt?: string;
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

export interface CampaignListEnvelope {
  version: 1;
  campaigns: CampaignRecord[];
}

export interface OpeningEnvelope {
  version: 1;
  campaignId: string;
  opening: OpeningDocument;
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
  | CampaignListEnvelope
  | OpeningEnvelope
  | SessionEnvelope
  | TurnAcceptedEnvelope
  | ControlPlaneEvent[];

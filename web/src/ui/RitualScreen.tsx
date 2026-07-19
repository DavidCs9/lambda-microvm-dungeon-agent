import { motion } from "framer-motion";
import { useState } from "react";
import { gameActions, useGameStore } from "../state/store";
import {
  EmberButton,
  ErrorLine,
  GhostButton,
  QuietMeta,
  ScreenShell,
  wsStatusLabel,
} from "./shared";

export function RitualScreen() {
  const playerId = useGameStore((s) => s.playerId);
  const wsStatus = useGameStore((s) => s.wsStatus);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const campaigns = useGameStore((s) => s.campaigns);
  const campaignsLoading = useGameStore((s) => s.campaignsLoading);
  const [busy, setBusy] = useState(false);
  const [resumingId, setResumingId] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);

  async function onForge() {
    if (busy || resumingId) return;
    setBusy(true);
    try {
      await gameActions.createCampaign();
    } finally {
      setBusy(false);
    }
  }

  async function onShowCampaigns() {
    if (busy || resumingId) return;
    setListOpen(true);
    await gameActions.loadCampaigns();
  }

  async function onResume(campaignId: string) {
    if (busy || resumingId) return;
    setResumingId(campaignId);
    try {
      await gameActions.resumeCampaign(campaignId);
    } finally {
      setResumingId(null);
    }
  }

  return (
    <ScreenShell className="text-center">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55 }}
        className="flex w-full flex-col items-center"
      >
        <p className="text-xs tracking-[0.28em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
          Ritual
        </p>
        <h1 className="mt-4 max-w-lg text-3xl leading-tight sm:text-4xl [font-family:var(--font-display)]">
          Forja el mundo
        </h1>
        <p className="mt-4 max-w-md text-base leading-relaxed text-[var(--muted)]">
          Antes de la primera escena, el fuego nombra un territorio y un destino.
          Cuando estés listo, forjamos la campaña.
        </p>

        <EmberButton disabled={busy || !!resumingId} onClick={() => void onForge()}>
          {busy ? "Forjando…" : "Forjar campaña"}
        </EmberButton>

        <GhostButton
          disabled={busy || campaignsLoading || !!resumingId}
          onClick={() => void onShowCampaigns()}
        >
          {campaignsLoading ? "Cargando…" : "Mis campañas"}
        </GhostButton>

        {listOpen && !campaignsLoading ? (
          <div className="mt-8 w-full max-w-sm text-left">
            {campaigns.length === 0 ? (
              <p className="text-center text-sm text-[var(--muted)]">Sin campañas listas</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {campaigns.map((campaign) => {
                  const shortId = campaign.campaignId.slice(-8);
                  const selected = resumingId === campaign.campaignId;
                  return (
                    <li key={campaign.campaignId}>
                      <button
                        type="button"
                        disabled={busy || !!resumingId}
                        onClick={() => void onResume(campaign.campaignId)}
                        className="flex w-full items-center justify-between border-b border-[var(--line)] px-1 py-3 text-left transition hover:border-[var(--ember)]/50 disabled:opacity-40"
                      >
                        <span className="text-base text-[var(--ink)] [font-family:var(--font-display)]">
                          {selected ? "Reanudando…" : `…${shortId}`}
                        </span>
                        <span className="text-xs tracking-[0.18em] text-[var(--muted)] uppercase">
                          {campaign.language}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ) : null}

        <ErrorLine message={errorMessage} />

        <QuietMeta>
          {playerId} · {wsStatusLabel(wsStatus)}
        </QuietMeta>
      </motion.div>
    </ScreenShell>
  );
}

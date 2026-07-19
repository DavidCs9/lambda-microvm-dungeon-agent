import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { gameActions, useGameStore } from "../state/store";
import { Card, EmberButton, ErrorLine, QuietMeta, ScreenShell, wsStatusLabel } from "./shared";

function formatDate(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("es", { day: "2-digit", month: "short", year: "numeric" });
}

export function RitualScreen() {
  const playerId = useGameStore((s) => s.playerId);
  const wsStatus = useGameStore((s) => s.wsStatus);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const campaigns = useGameStore((s) => s.campaigns);
  const campaignsLoading = useGameStore((s) => s.campaignsLoading);
  const [busy, setBusy] = useState(false);
  const [resumingId, setResumingId] = useState<string | null>(null);

  useEffect(() => {
    void gameActions.loadCampaigns();
  }, []);

  async function onForge() {
    if (busy || resumingId) return;
    setBusy(true);
    try {
      await gameActions.createCampaign();
    } finally {
      setBusy(false);
    }
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

        <ErrorLine message={errorMessage} />

        <div className="mt-14 w-full max-w-sm text-left">
          <p className="mb-4 text-center text-xs tracking-[0.22em] text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
            Campañas listas
          </p>

          {campaignsLoading ? (
            <p className="text-center text-sm text-[var(--muted)] [font-family:var(--font-ui)]">
              Cargando…
            </p>
          ) : campaigns.length === 0 ? (
            <p className="text-center text-sm text-[var(--muted)] [font-family:var(--font-ui)]">
              Aún no hay campañas. Forja la primera.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {campaigns.map((campaign) => {
                const title = campaign.openingTitle?.trim() || `…${campaign.campaignId.slice(-8)}`;
                const date = formatDate(campaign.createdAt);
                const meta = [date, campaign.language].filter(Boolean).join(" · ");
                return (
                  <li key={campaign.campaignId}>
                    <Card
                      title={resumingId === campaign.campaignId ? "Reanudando…" : title}
                      meta={meta}
                      disabled={busy || !!resumingId}
                      selected={resumingId === campaign.campaignId}
                      onClick={() => void onResume(campaign.campaignId)}
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <QuietMeta>
          {playerId} · {wsStatusLabel(wsStatus)}
        </QuietMeta>
      </motion.div>
    </ScreenShell>
  );
}

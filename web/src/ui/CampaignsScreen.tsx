import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { gameActions, useGameStore } from "../state/store";
import { MENU_COPY, humanCampaignStatus } from "./copy";
import { BackNav, Card, EmberButton, ErrorLine, QuietMeta, ScreenShell, wsStatusLabel } from "./shared";
import type { CreativeFamily } from "../net/types";

const FAMILY_OPTIONS: Array<{ value: CreativeFamily | "random"; label: string; description: string }> = [
  { value: "random", label: "Sorpresa", description: "Una familia elegida al azar" },
  { value: "action", label: "Acción", description: "Asedios, peligros y decisiones bajo presión" },
  { value: "exploration", label: "Exploración", description: "Ruinas, rutas imposibles y descubrimientos" },
  { value: "social", label: "Social", description: "Alianzas, conflictos y negociación" },
  { value: "mystery", label: "Misterio", description: "Secretos, pistas y verdades ocultas" },
];

function familyLabel(value: CreativeFamily | null | undefined): string {
  return FAMILY_OPTIONS.find((option) => option.value === value)?.label ?? "Sorpresa";
}

function formatDate(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("es", { day: "2-digit", month: "short", year: "numeric" });
}

export function CampaignsScreen() {
  const playerName = useGameStore((s) => s.playerName);
  const wsStatus = useGameStore((s) => s.wsStatus);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const campaigns = useGameStore((s) => s.campaigns);
  const campaignsLoading = useGameStore((s) => s.campaignsLoading);
  const [busy, setBusy] = useState(false);
  const [resumingId, setResumingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [creativeFamily, setCreativeFamily] = useState<CreativeFamily | "random">("random");

  useEffect(() => {
    void gameActions.loadCampaigns();
  }, []);

  const locked = busy || !!resumingId || !!deletingId;

  async function onCreate() {
    if (locked) return;
    setBusy(true);
    try {
      await gameActions.createCampaign(creativeFamily === "random" ? undefined : creativeFamily);
    } finally {
      setBusy(false);
    }
  }

  async function onResume(campaignId: string) {
    if (locked) return;
    setResumingId(campaignId);
    try {
      await gameActions.resumeCampaign(campaignId);
    } finally {
      setResumingId(null);
    }
  }

  async function onDelete(campaignId: string) {
    if (confirmId !== campaignId) {
      setConfirmId(campaignId);
      return;
    }
    setConfirmId(null);
    setDeletingId(campaignId);
    try {
      await gameActions.deleteCampaign(campaignId);
    } finally {
      setDeletingId(null);
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
        <BackNav onBack={() => gameActions.resetToMenu()} />

        <p className="mt-6 text-xs tracking-[0.28em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
          {MENU_COPY.manageCampaigns}
        </p>
        <h1 className="mt-4 max-w-lg text-3xl leading-tight sm:text-4xl [font-family:var(--font-display)]">
          Tus campañas
        </h1>
        <p className="mt-4 max-w-md text-base leading-relaxed text-[var(--muted)]">
          Crea un mundo nuevo, abre uno ya forjado o elimina los que no quieras.
        </p>

        <label className="mt-8 flex w-full max-w-md flex-col gap-2 text-left">
          <span className="text-xs tracking-[0.2em] text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
            Estilo de aventura
          </span>
          <select
            value={creativeFamily}
            onChange={(event) => setCreativeFamily(event.target.value as CreativeFamily | "random")}
            disabled={locked}
            className="border border-[var(--line)] bg-[var(--fog)] px-4 py-3 text-[var(--ink)] outline-none focus:border-[var(--ember)] [font-family:var(--font-ui)]"
          >
            {FAMILY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label} · {option.description}
              </option>
            ))}
          </select>
        </label>

        <EmberButton disabled={locked} onClick={() => void onCreate()}>
          {busy ? MENU_COPY.creatingCampaign : MENU_COPY.createCampaign}
        </EmberButton>

        <ErrorLine message={errorMessage} />

        <div className="mt-14 w-full max-w-md text-left">
          <p className="mb-4 text-center text-xs tracking-[0.22em] text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
            Tus campañas
          </p>

          {campaignsLoading ? (
            <p className="text-center text-sm text-[var(--muted)] [font-family:var(--font-ui)]">
              Cargando…
            </p>
          ) : campaigns.length === 0 ? (
            <p className="text-center text-sm text-[var(--muted)] [font-family:var(--font-ui)]">
              Aún no hay campañas. Usa «{MENU_COPY.createCampaign}» para forjar la primera.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {campaigns.map((campaign) => {
                const title = campaign.openingTitle?.trim() || `…${campaign.campaignId.slice(-8)}`;
                const ready = campaign.status === "ready";
                const date = formatDate(campaign.createdAt);
                const meta = [
                  date,
                  familyLabel(campaign.creativeFamily),
                  campaign.language,
                  humanCampaignStatus(campaign.status),
                ]
                  .filter(Boolean)
                  .join(" · ");
                const confirming = confirmId === campaign.campaignId;
                return (
                  <li key={campaign.campaignId} className="flex items-stretch gap-2">
                    <div className="min-w-0 flex-1">
                      <Card
                        title={resumingId === campaign.campaignId ? "Abriendo…" : title}
                        meta={ready ? meta : `${meta} · (no jugable)`}
                        disabled={locked || !ready}
                        selected={resumingId === campaign.campaignId}
                        onClick={() => void onResume(campaign.campaignId)}
                      />
                    </div>
                    {confirming ? (
                      <div className="flex shrink-0 flex-col">
                        <button
                          type="button"
                          disabled={locked}
                          onClick={() => void onDelete(campaign.campaignId)}
                          className="flex-1 border border-[var(--danger)]/60 px-3 text-xs tracking-wide text-[var(--danger)] uppercase transition hover:bg-[var(--danger)]/10 disabled:cursor-not-allowed disabled:opacity-40 [font-family:var(--font-ui)]"
                        >
                          {deletingId === campaign.campaignId
                            ? MENU_COPY.deleting
                            : MENU_COPY.confirmDelete}
                        </button>
                        <button
                          type="button"
                          disabled={locked}
                          onClick={() => setConfirmId(null)}
                          className="mt-1 flex-1 border border-[var(--line)] px-3 text-[0.7rem] tracking-wide text-[var(--muted)] uppercase transition hover:text-[var(--ink)] disabled:opacity-40 [font-family:var(--font-ui)]"
                        >
                          {MENU_COPY.cancel}
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() => setConfirmId(campaign.campaignId)}
                        className="shrink-0 border border-[var(--line)] px-3 text-xs tracking-wide text-[var(--muted)] uppercase transition hover:border-[var(--danger)]/60 hover:text-[var(--danger)] disabled:cursor-not-allowed disabled:opacity-40 [font-family:var(--font-ui)]"
                      >
                        {MENU_COPY.deleteCampaign}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <QuietMeta>
          {playerName} · {wsStatusLabel(wsStatus)}
        </QuietMeta>
      </motion.div>
    </ScreenShell>
  );
}

import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { gameActions, useGameStore } from "../state/store";
import { MENU_COPY, humanSessionStatus } from "./copy";
import {
  BackNav,
  Card,
  EmberButton,
  ErrorLine,
  GhostButton,
  GhostField,
  QuietMeta,
  ScreenShell,
  wsStatusLabel,
} from "./shared";

function formatDate(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("es", { day: "2-digit", month: "short", year: "numeric" });
}

export function MenuScreen() {
  const playerId = useGameStore((s) => s.playerId);
  const wsStatus = useGameStore((s) => s.wsStatus);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const activeSessions = useGameStore((s) => s.activeSessions);
  const activeSessionsLoading = useGameStore((s) => s.activeSessionsLoading);
  const campaigns = useGameStore((s) => s.campaigns);

  const [forging, setForging] = useState(false);
  const [resumingId, setResumingId] = useState<string | null>(null);
  const [abandoningId, setAbandoningId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const httpUrl = (import.meta.env.VITE_HTTP_URL ?? "").trim();
  const wsUrl = (import.meta.env.VITE_WS_URL ?? "").trim();
  const missingEnv = !httpUrl || !wsUrl;
  const canAct = playerId.trim().length >= 3 && !missingEnv;
  const busy = forging || !!resumingId || !!abandoningId;

  useEffect(() => {
    if (!missingEnv) {
      void gameActions.loadActiveSessions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function campaignTitle(campaignId: string | null | undefined): string {
    if (!campaignId) return "Partida";
    const campaign = campaigns.find((c) => c.campaignId === campaignId);
    return campaign?.openingTitle?.trim() || `…${campaignId.slice(-8)}`;
  }

  async function onCreate() {
    if (busy || !canAct) return;
    setForging(true);
    try {
      await gameActions.createCampaign();
    } finally {
      setForging(false);
    }
  }

  async function onResume(sessionId: string) {
    if (busy) return;
    setResumingId(sessionId);
    try {
      await gameActions.resumeSession(sessionId);
    } finally {
      setResumingId(null);
    }
  }

  async function onAbandon(sessionId: string) {
    if (busy) return;
    setAbandoningId(sessionId);
    try {
      await gameActions.abandonSession(sessionId);
    } finally {
      setAbandoningId(null);
    }
  }

  function onContinue() {
    if (busy || activeSessionsLoading || activeSessions.length === 0) return;
    if (activeSessions.length === 1) {
      void onResume(activeSessions[0].sessionId);
      return;
    }
    setPickerOpen(true);
  }

  const continueDisabled =
    !canAct || busy || activeSessionsLoading || activeSessions.length === 0;
  const continueReason =
    canAct && !activeSessionsLoading && activeSessions.length === 0
      ? MENU_COPY.continueEmptyReason
      : null;
  const showPicker = pickerOpen && activeSessions.length > 1;

  return (
    <ScreenShell className="text-center">
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
        className="flex w-full flex-col items-center"
      >
        <p
          className="text-[clamp(2.75rem,9vw,5.5rem)] leading-[0.95] tracking-[0.04em] text-[var(--ink)] [font-family:var(--font-display)]"
          style={{ textShadow: "0 0 60px rgba(217, 119, 58, 0.22)" }}
        >
          {MENU_COPY.brand}
        </p>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.25, duration: 0.6 }}
          className="mt-4 max-w-md text-base leading-relaxed text-[var(--muted)]"
        >
          {MENU_COPY.tagline}
        </motion.p>

        <GhostField
          id="player-id"
          label="Tu nombre en la mesa"
          value={playerId}
          minLength={3}
          placeholder="mínimo 3 caracteres"
          onChange={(v) => gameActions.setPlayerId(v)}
        />

        <div className="mt-10 flex w-full max-w-xs flex-col items-stretch gap-3">
          <EmberButton
            disabled={!canAct || busy}
            onClick={() => gameActions.goToCampaigns()}
            className="mt-0 w-full"
          >
            {MENU_COPY.newGame}
          </EmberButton>

          <div className="flex flex-col gap-1">
            <EmberButton
              disabled={continueDisabled}
              onClick={onContinue}
              className="mt-0 w-full"
            >
              {activeSessionsLoading ? MENU_COPY.continueSearching : MENU_COPY.continueGame}
            </EmberButton>
            {continueReason ? (
              <p className="text-xs text-[var(--muted)]">{continueReason}</p>
            ) : null}
          </div>

          <GhostButton
            disabled={!canAct || busy}
            onClick={() => void onCreate()}
            className="mt-0 w-full"
          >
            {forging ? MENU_COPY.creatingCampaign : MENU_COPY.createCampaign}
          </GhostButton>
        </div>

        <ErrorLine message={errorMessage} />

        {showPicker ? (
          <div className="mt-10 w-full max-w-sm text-left">
            <BackNav label={MENU_COPY.closePicker} onBack={() => setPickerOpen(false)} className="mb-4" />
            <p className="mb-4 text-center text-xs tracking-[0.22em] text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
              {MENU_COPY.pickerTitle}
            </p>
            <ul className="flex flex-col gap-3">
              {activeSessions.map((session) => (
                <li key={session.sessionId} className="flex items-stretch gap-2">
                  <div className="min-w-0 flex-1">
                    <Card
                      title={
                        resumingId === session.sessionId
                          ? MENU_COPY.resuming
                          : campaignTitle(session.campaignId)
                      }
                      meta={[formatDate(session.createdAt), humanSessionStatus(session.status)]
                        .filter(Boolean)
                        .join(" · ")}
                      disabled={busy}
                      selected={resumingId === session.sessionId}
                      onClick={() => void onResume(session.sessionId)}
                    />
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void onAbandon(session.sessionId)}
                    className="shrink-0 border border-[var(--line)] px-3 text-xs tracking-wide text-[var(--muted)] uppercase transition hover:border-[var(--danger)]/60 hover:text-[var(--danger)] disabled:cursor-not-allowed disabled:opacity-40 [font-family:var(--font-ui)]"
                  >
                    {abandoningId === session.sessionId ? MENU_COPY.abandoning : MENU_COPY.abandon}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {missingEnv ? (
          <p className="mt-8 max-w-sm text-sm leading-relaxed text-[var(--danger)]">
            Falta configurar el entorno: define VITE_HTTP_URL y VITE_WS_URL en
            web/.env.local.
          </p>
        ) : null}

        <QuietMeta>
          {playerId} · {wsStatusLabel(wsStatus)}
        </QuietMeta>
      </motion.div>
    </ScreenShell>
  );
}

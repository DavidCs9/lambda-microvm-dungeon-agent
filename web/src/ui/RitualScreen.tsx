import { motion } from "framer-motion";
import { useState } from "react";
import { gameActions, useGameStore } from "../state/store";
import { EmberButton, ErrorLine, QuietMeta, ScreenShell, wsStatusLabel } from "./shared";

export function RitualScreen() {
  const playerId = useGameStore((s) => s.playerId);
  const wsStatus = useGameStore((s) => s.wsStatus);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const [busy, setBusy] = useState(false);

  async function onForge() {
    if (busy) return;
    setBusy(true);
    try {
      await gameActions.createCampaign();
    } finally {
      setBusy(false);
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

        <EmberButton disabled={busy} onClick={() => void onForge()}>
          {busy ? "Forjando…" : "Forjar campaña"}
        </EmberButton>

        <ErrorLine message={errorMessage} />

        <QuietMeta>
          {playerId} · {wsStatusLabel(wsStatus)}
        </QuietMeta>
      </motion.div>
    </ScreenShell>
  );
}

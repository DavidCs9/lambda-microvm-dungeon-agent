import { motion } from "framer-motion";
import { gameActions, useGameStore } from "../state/store";
import { EmberButton, GhostField, ScreenShell } from "./shared";

export function LandingScreen() {
  const playerId = useGameStore((s) => s.playerId);
  const httpUrl = (import.meta.env.VITE_HTTP_URL ?? "").trim();
  const wsUrl = (import.meta.env.VITE_WS_URL ?? "").trim();
  const missingEnv = !httpUrl || !wsUrl;
  const canStart = playerId.trim().length >= 3 && !missingEnv;

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
          Dungeon Agent
        </p>

        <motion.h1
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.25, duration: 0.6 }}
          className="mt-8 max-w-lg text-2xl leading-snug text-[var(--ink)] sm:text-3xl [font-family:var(--font-display)]"
        >
          La mesa ya está puesta
        </motion.h1>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4, duration: 0.6 }}
          className="mt-4 max-w-md text-base leading-relaxed text-[var(--muted)]"
        >
          Una campaña narrada, dados en la sombra y el destino aún en blanco.
        </motion.p>

        <EmberButton
          disabled={!canStart}
          onClick={() => gameActions.beginRitual()}
        >
          Empezar
        </EmberButton>

        <GhostField
          id="player-id"
          label="Tu nombre en la mesa"
          value={playerId}
          minLength={3}
          placeholder="mínimo 3 caracteres"
          onChange={(v) => gameActions.setPlayerId(v)}
        />

        {missingEnv ? (
          <p className="mt-8 max-w-sm text-sm leading-relaxed text-[var(--danger)]">
            Falta configurar el entorno: define VITE_HTTP_URL y VITE_WS_URL en
            web/.env.local.
          </p>
        ) : null}
      </motion.div>
    </ScreenShell>
  );
}

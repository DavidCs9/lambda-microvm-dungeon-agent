import { motion } from "framer-motion";
import { gameActions, useGameStore } from "../state/store";
import { EmberButton, ScreenShell } from "./shared";

const COPY: Record<
  "won" | "lost" | "abandoned",
  { title: string; line: string }
> = {
  won: {
    title: "Victoria",
    line: "El fuego de la mesa celebra. Esta historia cierra en gloria.",
  },
  lost: {
    title: "Derrota",
    line: "La sombra prevaleció. Aún así, el relato queda grabado.",
  },
  abandoned: {
    title: "Abandonada",
    line: "Dejaste la mesa a medias. El mundo sigue, esperando otro intento.",
  },
};

export function OutcomeScreen() {
  const outcome = useGameStore((s) => s.outcome);
  const key = outcome === "won" || outcome === "lost" || outcome === "abandoned"
    ? outcome
    : "abandoned";
  const { title, line } = COPY[key];

  return (
    <ScreenShell className="text-center">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55 }}
        className="flex w-full flex-col items-center"
      >
        <p className="text-xs tracking-[0.28em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
          Desenlace
        </p>
        <h1 className="mt-5 text-4xl sm:text-5xl [font-family:var(--font-display)]">
          {title}
        </h1>
        <p className="mt-5 max-w-md text-base leading-relaxed text-[var(--muted)]">
          {line}
        </p>

        <EmberButton onClick={() => gameActions.resetToMenu()}>
          Volver al menú
        </EmberButton>
      </motion.div>
    </ScreenShell>
  );
}

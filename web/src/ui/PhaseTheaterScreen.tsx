import { motion } from "framer-motion";
import { useGameStore } from "../state/store";
import { ErrorLine, ScreenShell } from "./shared";

export function PhaseTheaterScreen() {
  const phaseLabel = useGameStore((s) => s.phaseLabel);
  const phaseKind = useGameStore((s) => s.phaseKind);
  const errorMessage = useGameStore((s) => s.errorMessage);

  const support =
    phaseKind === "session"
      ? "La mesa se prepara. El MicroVM despierta y el mundo se ancla."
      : phaseKind === "campaign"
        ? "El territorio toma forma. Espera mientras el ritual avanza."
        : "Algo se está tejiendo tras el velo.";

  const display = phaseLabel?.trim() || "En marcha…";

  return (
    <ScreenShell className="text-center">
      <motion.div
        key={`${phaseKind ?? "none"}:${display}`}
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.45 }}
        className="flex w-full flex-col items-center"
      >
        <p className="text-xs tracking-[0.28em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
          {phaseKind === "session" ? "Sesión" : "Campaña"}
        </p>

        <h1 className="mt-6 max-w-2xl text-[clamp(1.75rem,5vw,3rem)] leading-tight [font-family:var(--font-display)]">
          {display}
        </h1>

        <p className="mt-5 max-w-md text-base leading-relaxed text-[var(--muted)]">
          {support}
        </p>

        <motion.div
          className="mt-12 h-px w-40 origin-center bg-[var(--ember)]/70"
          initial={{ scaleX: 0.2, opacity: 0.4 }}
          animate={{ scaleX: [0.25, 1, 0.35], opacity: [0.35, 0.95, 0.45] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
        />

        <motion.div
          className="mt-6 h-1.5 w-1.5 rounded-full bg-[var(--ember)]"
          animate={{ opacity: [0.3, 1, 0.3], scale: [0.85, 1.15, 0.85] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
        />

        <ErrorLine message={errorMessage} />
      </motion.div>
    </ScreenShell>
  );
}

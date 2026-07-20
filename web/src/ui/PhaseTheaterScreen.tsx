import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { gameActions, useGameStore } from "../state/store";
import { humanPhase } from "./copy";
import { BackNav, ErrorLine, ScreenShell } from "./shared";

const STEPS = ["Forjar", "Despertar", "Umbral", "Mesa"];

function spineStep(phaseKind: string | null, phaseLabel: string | null): number {
  if (phaseKind === "campaign") return 0;
  if (phaseKind !== "session") return 0;
  const phase = phaseLabel?.trim() ?? "";
  if (phase === "initializing_game" || phase === "ready") return 2;
  return 1;
}

export function PhaseTheaterScreen() {
  const phaseLabel = useGameStore((s) => s.phaseLabel);
  const phaseKind = useGameStore((s) => s.phaseKind);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    setElapsed(0);
    const start = Date.now();
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [phaseKind]);

  const activeStep = spineStep(phaseKind, phaseLabel);
  const display = humanPhase(phaseLabel, phaseKind);

  const support =
    phaseKind === "session"
      ? "La mesa se prepara. El MicroVM despierta y el mundo se ancla."
      : phaseKind === "campaign"
        ? "El territorio toma forma. Espera mientras el ritual avanza."
        : "Algo se está tejiendo tras el velo.";

  return (
    <ScreenShell className="text-center">
      <BackNav onBack={() => gameActions.resetToMenu()} className="mb-6" />
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

        <div className="mt-10 flex items-center gap-3 [font-family:var(--font-ui)]">
          {STEPS.map((step, index) => (
            <span
              key={step}
              className={`text-xs tracking-[0.16em] uppercase ${
                index === activeStep
                  ? "text-[var(--ember)]"
                  : index < activeStep
                    ? "text-[var(--muted)]"
                    : "text-[var(--muted)]/40"
              }`}
            >
              {step}
              {index < STEPS.length - 1 && <span className="mx-2 opacity-40">·</span>}
            </span>
          ))}
        </div>

        <p className="mt-4 text-xs tabular-nums text-[var(--muted)]/70 [font-family:var(--font-ui)]">
          {elapsed}s
        </p>

        <motion.div
          className="mt-8 h-px w-40 origin-center bg-[var(--ember)]/70"
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

import { AnimatePresence, motion } from "framer-motion";
import { useState, type FormEvent } from "react";
import { gameActions, useGameStore } from "../state/store";
import { EmberButton, ErrorLine } from "./shared";

export function PlayTableScreen() {
  const narrationStream = useGameStore((s) => s.narrationStream);
  const turnLog = useGameStore((s) => s.turnLog);
  const turnPending = useGameStore((s) => s.turnPending);
  const diceBeat = useGameStore((s) => s.diceBeat);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const [action, setAction] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const locked = turnPending || submitting;
  const canSubmit = action.trim().length > 0 && !locked;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    const text = action.trim();
    setSubmitting(true);
    try {
      await gameActions.submitAction(text);
      setAction("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative mx-auto flex min-h-screen w-full max-w-3xl flex-col px-5 py-10 sm:px-8">
      <header className="mb-8 text-center">
        <p className="text-xs tracking-[0.28em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
          Mesa
        </p>
        <h1 className="mt-3 text-2xl [font-family:var(--font-display)] sm:text-3xl">
          Tu turno en la historia
        </h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Habla con el mundo. Los dados responderán cuando haga falta.
        </p>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-8">
        <section aria-live="polite" className="space-y-6">
          {turnLog.map((entry) => (
            <motion.article
              key={entry.turnId}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="border-l border-[var(--line)] pl-4"
            >
              {typeof entry.roll === "number" && (
                <p className="mb-2 text-xs tracking-wide text-[var(--muted)]">
                  Tirada {entry.roll}
                  {typeof entry.success === "boolean"
                    ? entry.success
                      ? " · éxito"
                      : " · fallo"
                    : ""}
                </p>
              )}
              <p className="text-base leading-[1.75] whitespace-pre-wrap text-[var(--ink)]">
                {entry.narration}
              </p>
            </motion.article>
          ))}

          {(narrationStream || turnPending) && (
            <motion.article
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="border-l border-[var(--ember)]/40 pl-4"
            >
              <p className="mb-2 text-xs tracking-[0.2em] text-[var(--ember)] uppercase">
                {turnPending && !narrationStream ? "Escuchando…" : "Narración"}
              </p>
              <p className="text-base leading-[1.75] whitespace-pre-wrap text-[var(--ink)]">
                {narrationStream || "…"}
              </p>
            </motion.article>
          )}

          {turnLog.length === 0 && !narrationStream && !turnPending && (
            <p className="text-center text-[var(--muted)]">
              El silencio de la taberna espera tu primera acción.
            </p>
          )}
        </section>

        <form onSubmit={(e) => void onSubmit(e)} className="mt-auto pt-4">
          <label className="block">
            <span className="sr-only">Tu acción</span>
            <textarea
              value={action}
              onChange={(e) => setAction(e.target.value)}
              disabled={locked}
              rows={3}
              placeholder="¿Qué haces?"
              className="w-full resize-y border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-base leading-relaxed text-[var(--ink)] outline-none placeholder:text-[var(--muted)]/60 focus:border-[var(--ember)]/50 disabled:opacity-50"
            />
          </label>
          <div className="flex justify-center">
            <EmberButton type="submit" disabled={!canSubmit} className="mt-5">
              {locked ? "En curso…" : "Declarar acción"}
            </EmberButton>
          </div>
          <ErrorLine message={errorMessage} />
        </form>
      </div>

      <AnimatePresence>
        {diceBeat && (
          <motion.div
            key={diceBeat.turnId}
            role="dialog"
            aria-modal="true"
            aria-label="Resultado de dados"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 flex items-center justify-center bg-[var(--deep)]/75 px-6 backdrop-blur-[2px]"
            onClick={() => gameActions.dismissDiceBeat()}
          >
            <motion.div
              initial={{ opacity: 0, y: 24, scale: 0.94 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -12, scale: 0.98 }}
              transition={{ type: "spring", stiffness: 280, damping: 24 }}
              className="w-full max-w-sm text-center"
              onClick={(e) => e.stopPropagation()}
            >
              <p className="text-xs tracking-[0.3em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
                Dados
              </p>
              <p
                className="mt-4 text-6xl tabular-nums text-[var(--ink)] [font-family:var(--font-display)]"
                style={{ textShadow: "0 0 40px rgba(217, 119, 58, 0.35)" }}
              >
                {diceBeat.roll}
              </p>
              <p className="mt-3 text-base text-[var(--muted)]">
                Dificultad {diceBeat.difficulty}
              </p>
              <p
                className={`mt-5 text-xl tracking-wide [font-family:var(--font-display)] ${
                  diceBeat.success ? "text-[var(--ember)]" : "text-[#e8a07a]"
                }`}
              >
                {diceBeat.success ? "Éxito" : "Fallo"}
              </p>
              <button
                type="button"
                onClick={() => gameActions.dismissDiceBeat()}
                className="mt-8 text-sm tracking-[0.18em] text-[var(--muted)] uppercase underline-offset-4 hover:text-[var(--ink)] hover:underline"
              >
                Continuar
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

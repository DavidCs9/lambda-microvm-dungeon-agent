import { motion } from "framer-motion";
import { useMemo } from "react";
import { gameActions, useGameStore } from "../state/store";
import { EmberButton, ErrorLine, ScreenShell } from "./shared";

export function OpeningScrollScreen() {
  const opening = useGameStore((s) => s.opening);
  const errorMessage = useGameStore((s) => s.errorMessage);

  const blocks = useMemo(() => {
    const list = opening?.blocks ?? [];
    return [...list].sort((a, b) => a.position - b.position);
  }, [opening]);

  const title = opening?.title?.trim() || "El umbral";

  return (
    <ScreenShell align="start" className="pb-24 pt-12">
      <motion.header
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-12 text-center"
      >
        <p className="text-xs tracking-[0.28em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
          Apertura
        </p>
        <h1 className="mt-4 text-3xl leading-tight sm:text-4xl [font-family:var(--font-display)]">
          {title}
        </h1>
        <p className="mt-3 text-base text-[var(--muted)]">
          Lee con calma. El mundo se revela por fragmentos.
        </p>
      </motion.header>

      <div className="mx-auto flex w-full max-w-2xl flex-col gap-10">
        {blocks.map((block, index) => (
          <motion.article
            key={block.id}
            initial={{ opacity: 0, y: 28 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-8% 0px -8% 0px" }}
            transition={{ duration: 0.55, delay: Math.min(index * 0.04, 0.24) }}
          >
            <p className="mb-3 text-[0.7rem] tracking-[0.24em] text-[var(--ember)]/80 uppercase [font-family:var(--font-display)]">
              {kindLabel(block.kind)}
            </p>
            <p className="text-lg leading-[1.75] text-[var(--ink)] whitespace-pre-wrap">
              {block.text}
            </p>
          </motion.article>
        ))}

        {blocks.length === 0 && (
          <p className="text-center text-[var(--muted)]">
            El pergamino aún está en blanco…
          </p>
        )}
      </div>

      <div className="mt-16 flex flex-col items-center">
        <EmberButton onClick={() => gameActions.continueFromOpening()}>
          Comenzar la aventura
        </EmberButton>
        <ErrorLine message={errorMessage} />
      </div>
    </ScreenShell>
  );
}

function kindLabel(kind: string): string {
  const map: Record<string, string> = {
    identity: "Identidad",
    background: "Trasfondo",
    motivation: "Motivación",
    knowledge: "Saber",
    situation: "Situación",
    possible_action: "Posible acción",
  };
  return map[kind] ?? kind.replace(/_/g, " ");
}

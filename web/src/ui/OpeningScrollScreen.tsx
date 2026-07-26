import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { isVoiceEnabled } from "../game/audio";
import { toggleVoice } from "../game/narrationVoice";
import { gameActions, useGameStore } from "../state/store";
import { MENU_COPY, openingKindLabel } from "./copy";
import { BackNav, EmberButton, ErrorLine, ScreenShell, VoiceToggle } from "./shared";

export function OpeningScrollScreen() {
  const opening = useGameStore((s) => s.opening);
  const portraitUrl = useGameStore((s) => s.portraitUrl);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const [voiceOn, setVoiceOn] = useState(isVoiceEnabled);

  useEffect(() => {
    gameActions.ensurePortrait();
  }, []);

  const blocks = useMemo(() => {
    const list = opening?.blocks ?? [];
    // Stats and inventory are compact rail context, not narrative scroll fragments.
    return [...list]
      .filter((block) => block.kind !== "stats" && block.kind !== "inventory")
      .sort((a, b) => a.position - b.position);
  }, [opening]);

  const title = opening?.title?.trim() || "El umbral";
  const premise = blocks.find((block) => block.kind === "premise");
  const objective = blocks.find((block) => block.kind === "objective");
  const situation = blocks.find((block) => block.kind === "situation");
  const summaryIds = new Set([premise?.id, objective?.id, situation?.id]);
  const contextBlocks = blocks.filter((block) => !summaryIds.has(block.id));

  return (
    <ScreenShell align="start" className="pb-32 pt-12">
      <BackNav
        label={MENU_COPY.backToCampaigns}
        onBack={() => gameActions.goToCampaigns()}
        className="mb-8"
      />
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
        {portraitUrl && (
          <div className="mx-auto mt-6 aspect-square w-full max-w-[180px] overflow-hidden rounded-lg border border-[var(--line)] shadow-[0_0_32px_rgba(0,0,0,0.4)]">
            <img
              src={portraitUrl}
              alt="Retrato del personaje"
              className="h-full w-full object-cover"
            />
          </div>
        )}
        <p className="mt-3 text-base text-[var(--muted)]">
          Lee con calma. El mundo se revela por fragmentos.
        </p>
      </motion.header>

      <div className="mx-auto flex w-full max-w-2xl flex-col gap-10">
        {(premise || objective || situation) && (
          <motion.section
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55 }}
            className="rounded-xl border border-[var(--line)] bg-[var(--surface-2)]/75 px-6 py-7 shadow-[0_18px_60px_rgba(0,0,0,0.24)] sm:px-9"
          >
            <p className="mb-4 text-[0.7rem] tracking-[0.24em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
              La aventura
            </p>
            {premise && <p className="text-xl leading-relaxed text-[var(--ink)]">{premise.text}</p>}
            {objective && (
              <div className="mt-6 border-t border-[var(--line)] pt-5">
                <p className="mb-2 text-[0.65rem] tracking-[0.2em] text-[var(--muted)] uppercase">
                  Objetivo
                </p>
                <p className="text-base leading-relaxed text-[var(--ink)]/90">{objective.text}</p>
              </div>
            )}
            {situation && (
              <div className="mt-6 border-t border-[var(--line)] pt-5">
                <p className="mb-2 text-[0.65rem] tracking-[0.2em] text-[var(--muted)] uppercase">
                  Ahora mismo
                </p>
                <p className="text-base leading-relaxed text-[var(--ink)]/90">{situation.text}</p>
              </div>
            )}
          </motion.section>
        )}

        {contextBlocks.map((block, index) => (
          <motion.article
            key={block.id}
            initial={{ opacity: 0, y: 28 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-8% 0px -8% 0px" }}
            transition={{ duration: 0.55, delay: Math.min(index * 0.04, 0.24) }}
          >
            <p className="mb-3 text-[0.7rem] tracking-[0.24em] text-[var(--ember)]/80 uppercase [font-family:var(--font-display)]">
              {openingKindLabel(block.kind)}
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

      <div className="fixed inset-x-0 bottom-0 z-20 flex max-h-[40dvh] flex-col items-center overflow-y-auto border-t border-[var(--line)] bg-[var(--surface-2)] px-5 pt-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] backdrop-blur-sm sm:px-6 sm:pt-4">
        <VoiceToggle
          enabled={voiceOn}
          onToggle={() => setVoiceOn(toggleVoice())}
          className="mb-3"
        />
        <EmberButton onClick={() => gameActions.continueFromOpening()} className="mt-0 w-full max-w-sm">
          Comenzar la aventura
        </EmberButton>
        <ErrorLine message={errorMessage} />
      </div>
    </ScreenShell>
  );
}

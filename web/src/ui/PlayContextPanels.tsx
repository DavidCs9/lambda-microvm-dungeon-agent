import type { ReactNode } from "react";
import { useMemo } from "react";
import type { OpeningBlock, OpeningDocument } from "../net/types";

const MAX_CHARS = 140;
const MAX_KNOWLEDGE = 2;
const MAX_ACTIONS = 3;

function truncate(text: string, max = MAX_CHARS): string {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1).trimEnd()}…`;
}

function blocksOfKind(
  opening: OpeningDocument | null | undefined,
  kind: OpeningBlock["kind"],
): OpeningBlock[] {
  return [...(opening?.blocks ?? [])]
    .filter((block) => block.kind === kind)
    .sort((a, b) => a.position - b.position);
}

function RailShell({
  align,
  children,
}: {
  align: "left" | "right";
  children: ReactNode;
}) {
  const border =
    align === "left" ? "border-r border-[var(--line)]" : "border-l border-[var(--line)]";
  return (
    <aside
      className={`hidden min-h-0 w-52 shrink-0 overflow-y-auto bg-[var(--panel)] px-4 py-5 xl:w-60 lg:block ${border}`}
    >
      {children}
    </aside>
  );
}

function RailTitle({ children }: { children: ReactNode }) {
  return (
    <p className="mb-4 text-[0.65rem] tracking-[0.28em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
      {children}
    </p>
  );
}

export function CampaignContextPanel({
  opening,
}: {
  opening: OpeningDocument | null | undefined;
}) {
  const situation = useMemo(() => {
    const [block] = blocksOfKind(opening, "situation");
    return block ? truncate(block.text) : null;
  }, [opening]);

  const knowledge = useMemo(
    () => blocksOfKind(opening, "knowledge").slice(0, MAX_KNOWLEDGE),
    [opening],
  );

  const actions = useMemo(
    () => blocksOfKind(opening, "possible_action").slice(0, MAX_ACTIONS),
    [opening],
  );

  if (!situation && knowledge.length === 0 && actions.length === 0) return null;

  return (
    <RailShell align="left">
      <RailTitle>Campaña</RailTitle>
      <div className="space-y-5">
        {situation && (
          <p className="text-sm leading-relaxed text-[var(--ink)]/85">{situation}</p>
        )}

        {knowledge.length > 0 && (
          <section>
            <p className="mb-2 text-[0.65rem] tracking-[0.2em] text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
              Saber
            </p>
            <ul className="space-y-2">
              {knowledge.map((block) => (
                <li
                  key={block.id}
                  className="text-sm leading-relaxed text-[var(--ink)]/85"
                >
                  {truncate(block.text)}
                </li>
              ))}
            </ul>
          </section>
        )}

        {actions.length > 0 && (
          <section>
            <p className="mb-2 text-[0.65rem] tracking-[0.2em] text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
              Posibles acciones
            </p>
            <ul className="space-y-1.5">
              {actions.map((block) => (
                <li
                  key={block.id}
                  className="rounded border border-[var(--line)] bg-[var(--surface-2)]/60 px-2 py-1 text-xs leading-snug text-[var(--ink)]/85"
                >
                  {truncate(block.text, 100)}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </RailShell>
  );
}

export function CharacterContextPanel({
  opening,
  portraitUrl,
}: {
  opening: OpeningDocument | null | undefined;
  portraitUrl?: string | null;
}) {
  const identity = useMemo(() => {
    const [block] = blocksOfKind(opening, "identity");
    return block ? block.text.trim() : null;
  }, [opening]);

  const motivation = useMemo(() => {
    const [block] = blocksOfKind(opening, "motivation");
    return block ? truncate(block.text, 160) : null;
  }, [opening]);

  if (!portraitUrl && !identity && !motivation) return null;

  return (
    <RailShell align="right">
      <RailTitle>Personaje</RailTitle>
      {portraitUrl && (
        <div className="mb-5 aspect-square w-full max-w-[180px] overflow-hidden rounded-lg border border-[var(--line)] shadow-[0_0_24px_rgba(0,0,0,0.35)]">
          <img
            src={portraitUrl}
            alt="Retrato del personaje"
            className="h-full w-full object-cover"
          />
        </div>
      )}
      <div className="space-y-4">
        {identity && (
          <p className="text-sm leading-relaxed text-[var(--ink)]/85 whitespace-pre-wrap">
            {identity}
          </p>
        )}
        {motivation && (
          <section>
            <p className="mb-1.5 text-[0.65rem] tracking-[0.2em] text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
              Motivación
            </p>
            <p className="text-sm leading-relaxed text-[var(--ink)]/85">{motivation}</p>
          </section>
        )}
      </div>
    </RailShell>
  );
}

import { useMemo } from "react";
import type { OpeningBlock, OpeningBlockKind, OpeningDocument } from "../net/types";
import { openingKindLabel } from "./copy";

const CAMPAIGN_KINDS: OpeningBlockKind[] = [
  "situation",
  "knowledge",
  "possible_action",
];

const CHARACTER_KINDS: OpeningBlockKind[] = [
  "identity",
  "background",
  "motivation",
];

function blocksForKinds(
  opening: OpeningDocument | null | undefined,
  kinds: OpeningBlockKind[],
): OpeningBlock[] {
  const wanted = new Set(kinds);
  return [...(opening?.blocks ?? [])]
    .filter((block) => wanted.has(block.kind))
    .sort((a, b) => a.position - b.position);
}

function groupByKind(blocks: OpeningBlock[]): { kind: OpeningBlockKind; texts: string[] }[] {
  const order: OpeningBlockKind[] = [];
  const texts = new Map<OpeningBlockKind, string[]>();
  for (const block of blocks) {
    const list = texts.get(block.kind);
    if (!list) {
      order.push(block.kind);
      texts.set(block.kind, [block.text]);
    } else {
      list.push(block.text);
    }
  }
  return order.map((kind) => ({ kind, texts: texts.get(kind) ?? [] }));
}

function ContextPanel({
  title,
  blocks,
  align,
}: {
  title: string;
  blocks: OpeningBlock[];
  align: "left" | "right";
}) {
  const groups = useMemo(() => groupByKind(blocks), [blocks]);
  const border =
    align === "left" ? "border-r border-[var(--line)]" : "border-l border-[var(--line)]";

  if (groups.length === 0) return null;

  return (
    <aside
      className={`hidden min-h-0 w-52 shrink-0 overflow-y-auto bg-[var(--panel)] px-4 py-5 xl:w-60 lg:block ${border}`}
    >
      <p className="mb-5 text-[0.65rem] tracking-[0.28em] text-[var(--ember)] uppercase [font-family:var(--font-display)]">
        {title}
      </p>
      <div className="space-y-5">
        {groups.map((group) => (
          <section key={group.kind}>
            <p className="mb-2 text-[0.65rem] tracking-[0.2em] text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
              {openingKindLabel(group.kind)}
            </p>
            <ul className="space-y-2.5">
              {group.texts.map((text, index) => (
                <li
                  key={`${group.kind}-${index}`}
                  className="text-sm leading-relaxed text-[var(--ink)]/85 whitespace-pre-wrap"
                >
                  {group.kind === "possible_action" ? `· ${text}` : text}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  );
}

export function CampaignContextPanel({
  opening,
}: {
  opening: OpeningDocument | null | undefined;
}) {
  const blocks = useMemo(
    () => blocksForKinds(opening, CAMPAIGN_KINDS),
    [opening],
  );
  return <ContextPanel title="Campaña" blocks={blocks} align="left" />;
}

export function CharacterContextPanel({
  opening,
}: {
  opening: OpeningDocument | null | undefined;
}) {
  const blocks = useMemo(
    () => blocksForKinds(opening, CHARACTER_KINDS),
    [opening],
  );
  return <ContextPanel title="Personaje" blocks={blocks} align="right" />;
}

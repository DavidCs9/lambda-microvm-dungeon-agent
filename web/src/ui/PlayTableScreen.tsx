import { useEffect, useRef, useState } from "react";
import { isVoiceEnabled } from "../game/audio";
import { toggleVoice } from "../game/narrationVoice";
import { gameActions, useGameStore } from "../state/store";
import {
  CampaignContextPanel,
  CharacterContextPanel,
} from "./PlayContextPanels";
import {
  AppShell,
  Composer,
  ContextBar,
  DiceChip,
  TranscriptEntry,
} from "./shared";

export function PlayTableScreen() {
  const opening = useGameStore((s) => s.opening);
  const portraitUrl = useGameStore((s) => s.portraitUrl);
  const inventory = useGameStore((s) => s.inventory);
  const stats = useGameStore((s) => s.stats);
  const campaign = useGameStore((s) => s.campaign);
  const narrationStream = useGameStore((s) => s.narrationStream);
  const turnLog = useGameStore((s) => s.turnLog);
  const turnPending = useGameStore((s) => s.turnPending);
  const wsStatus = useGameStore((s) => s.wsStatus);
  const errorMessage = useGameStore((s) => s.errorMessage);
  const [action, setAction] = useState("");
  const [pendingAction, setPendingAction] = useState("");
  const [pendingSince, setPendingSince] = useState<number | null>(null);
  const [pendingSeconds, setPendingSeconds] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [confirmExit, setConfirmExit] = useState(false);
  const [followBottom, setFollowBottom] = useState(true);
  const [voiceOn, setVoiceOn] = useState(isVoiceEnabled);

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const submittedTurnCount = useRef(0);

  const locked = turnPending || submitting;
  const canSubmit = action.trim().length > 0 && !locked;
  const waitingCopy =
    pendingSeconds >= 8
      ? {
          label: "La mesa sigue procesando tu acción.",
          detail: "No la envíes de nuevo.",
        }
      : pendingSeconds >= 4
        ? {
            label: "La respuesta toma forma…",
            detail: "El mundo se acomoda a tu decisión.",
          }
        : {
            label: "El Master está pensando…",
            detail: "La acción fue recibida.",
          };

  const title =
    opening?.title?.trim() ||
    (campaign ? `…${campaign.campaignId.slice(-8)}` : "La mesa");

  async function onSubmit() {
    if (!canSubmit) return;
    const text = action.trim();
    submittedTurnCount.current = turnLog.length;
    setPendingAction(text);
    setPendingSince(Date.now());
    setPendingSeconds(0);
    setSubmitting(true);
    try {
      await gameActions.submitAction(text);
      setAction("");
    } finally {
      setSubmitting(false);
    }
  }

  function onExit() {
    if (!confirmExit) {
      setConfirmExit(true);
      return;
    }
    // Leave the table without abandoning: session stays active for Continuar.
    gameActions.resetToMenu();
  }

  useEffect(() => {
    if (!confirmExit) return;
    const timer = window.setTimeout(() => setConfirmExit(false), 3000);
    return () => window.clearTimeout(timer);
  }, [confirmExit]);

  useEffect(() => {
    if (!pendingSince) return;
    const timer = window.setInterval(() => {
      setPendingSeconds(Math.floor((Date.now() - pendingSince) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [pendingSince]);

  useEffect(() => {
    if (!pendingAction) return;
    if (turnLog.length > submittedTurnCount.current || (errorMessage && !locked)) {
      setPendingAction("");
      setPendingSince(null);
      setPendingSeconds(0);
    }
  }, [errorMessage, locked, pendingAction, turnLog.length]);

  useEffect(() => {
    gameActions.ensurePortrait();
  }, []);

  useEffect(() => {
    if (!followBottom) return;
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [turnLog, narrationStream, followBottom]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setFollowBottom(distanceFromBottom < 48);
  }

  function jumpToBottom() {
    setFollowBottom(true);
    bottomRef.current?.scrollIntoView({ block: "end" });
  }

  return (
    <AppShell
      header={
        <ContextBar
          title={title}
          turnCount={turnLog.length}
          wsStatus={wsStatus}
          onExit={onExit}
          voiceEnabled={voiceOn}
          onVoiceToggle={() => setVoiceOn(toggleVoice())}
        />
      }
      leftRail={<CampaignContextPanel opening={opening} />}
      rightRail={
        <CharacterContextPanel
          opening={opening}
          portraitUrl={portraitUrl}
          inventory={inventory}
          stats={stats}
        />
      }
      footer={
        <Composer
          value={action}
          onChange={setAction}
          onSubmit={() => void onSubmit()}
          disabled={locked}
          error={errorMessage}
          lockedLabel={waitingCopy.label}
        />
      }
    >
      <div className="flex shrink-0 flex-col border-b border-[var(--line)] bg-[var(--surface-1)] lg:hidden">
        <details className="group border-b border-[var(--line)] last:border-b-0">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-4 py-2 text-xs tracking-[0.16em] text-[var(--muted)] uppercase [font-family:var(--font-ui)] marker:hidden">
            <span>Contexto de campaña</span>
            <span className="text-[var(--ember)] transition group-open:rotate-45">+</span>
          </summary>
          <CampaignContextPanel opening={opening} mobile />
        </details>
        <details className="group">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-4 py-2 text-xs tracking-[0.16em] text-[var(--muted)] uppercase [font-family:var(--font-ui)] marker:hidden">
            <span>Personaje e inventario</span>
            <span className="text-[var(--ember)] transition group-open:rotate-45">+</span>
          </summary>
          <CharacterContextPanel
            opening={opening}
            portraitUrl={portraitUrl}
            inventory={inventory}
            stats={stats}
            mobile
          />
        </details>
      </div>

      {confirmExit && (
        <div className="shrink-0 border-b border-[var(--line)] bg-[var(--surface-2)] px-4 py-2 text-center text-xs text-[var(--muted)] [font-family:var(--font-ui)]">
          ¿Volver al menú? La partida queda en pausa; usa Continuar para retomar.
        </div>
      )}

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="relative flex-1 overflow-y-auto px-5 py-6 sm:px-8"
      >
        <div className="space-y-6">
          {turnLog.length === 0 && !narrationStream && !turnPending && (
            <p className="text-center text-[var(--muted)]">
              El silencio de la taberna espera tu primera acción.
            </p>
          )}

          {turnLog.map((entry) => (
            <TranscriptEntry key={entry.turnId} action={entry.action} narration={entry.narration}>
              {typeof entry.roll === "number" && (
                <DiceChip
                  roll={entry.roll}
                  success={entry.success}
                  modifier={entry.modifier}
                  stat={entry.stat}
                />
              )}
            </TranscriptEntry>
          ))}

          {(narrationStream || turnPending || submitting || pendingAction) && (
            <article
              aria-live="polite"
              className="border-l border-[var(--ember)]/40 pl-4"
            >
              {pendingAction && !narrationStream && (
                <p className="mb-4 text-sm text-[var(--muted)] [font-family:var(--font-ui)]">
                  » {pendingAction}
                </p>
              )}
              <p className="mb-2 text-xs tracking-[0.2em] text-[var(--ember)] uppercase [font-family:var(--font-ui)]">
                {narrationStream ? "El Master responde…" : waitingCopy.label}
              </p>
              <p className="text-base leading-[1.75] whitespace-pre-wrap text-[var(--ink)]">
                {narrationStream || (
                  <>
                    <span className="animate-pulse">•••</span>
                    <span className="ml-3 text-sm text-[var(--muted)]">{waitingCopy.detail}</span>
                  </>
                )}
              </p>
            </article>
          )}
        </div>
        <div ref={bottomRef} />
      </div>

      {!followBottom && (
        <button
          type="button"
          onClick={jumpToBottom}
          className="absolute bottom-24 left-1/2 -translate-x-1/2 rounded-full border border-[var(--line)] bg-[var(--surface-2)] px-4 py-1.5 text-xs tracking-wide text-[var(--muted)] shadow-lg [font-family:var(--font-ui)] hover:text-[var(--ink)]"
        >
          ↓ Ir al final
        </button>
      )}
    </AppShell>
  );
}

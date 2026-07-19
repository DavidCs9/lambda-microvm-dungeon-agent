import type { KeyboardEvent, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

export type WsStatus = "disconnected" | "connecting" | "connected" | "error";

const WS_LABELS: Record<WsStatus, string> = {
  disconnected: "desconectado",
  connecting: "conectando",
  connected: "conectado",
  error: "error",
};

export function wsStatusLabel(status: WsStatus): string {
  return WS_LABELS[status] ?? status;
}

export function ScreenShell({
  children,
  className = "",
  align = "center",
}: {
  children: ReactNode;
  className?: string;
  align?: "center" | "start";
}) {
  const alignClass =
    align === "center" ? "items-center justify-center" : "items-stretch justify-start";
  return (
    <div
      className={`relative mx-auto flex min-h-screen w-full max-w-3xl flex-col px-6 py-16 sm:px-10 ${alignClass} ${className}`}
    >
      {children}
    </div>
  );
}

export function QuietMeta({ children }: { children: ReactNode }) {
  return (
    <p className="mt-8 text-center text-sm tracking-wide text-[var(--muted)] opacity-80">
      {children}
    </p>
  );
}

export function ErrorLine({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="mt-6 max-w-md text-center text-sm leading-relaxed text-[var(--danger)] [font-family:var(--font-ui)]"
    >
      {message}
    </p>
  );
}

export function EmberButton({
  children,
  onClick,
  disabled,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`relative mt-8 inline-flex min-h-12 items-center justify-center border border-[var(--ember)]/70 bg-[var(--ember)]/15 px-10 py-3 text-base tracking-[0.18em] text-[var(--ink)] uppercase transition duration-300 [font-family:var(--font-display)] hover:bg-[var(--ember)]/30 hover:border-[var(--ember)] disabled:cursor-not-allowed disabled:opacity-40 ${className}`}
    >
      {children}
    </button>
  );
}

export function GhostButton({
  children,
  onClick,
  disabled,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`relative mt-4 inline-flex min-h-12 items-center justify-center border border-[var(--line)] bg-transparent px-10 py-3 text-base tracking-[0.18em] text-[var(--muted)] uppercase transition duration-300 [font-family:var(--font-display)] hover:border-[var(--ember)]/60 hover:text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-40 ${className}`}
    >
      {children}
    </button>
  );
}

export function AppShell({
  children,
  className = "",
  header,
  footer,
}: {
  children: ReactNode;
  className?: string;
  header?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div
      className={`mx-auto flex h-[100dvh] w-full max-w-3xl flex-col overflow-hidden pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] ${className}`}
    >
      {header}
      <div className="relative flex min-h-0 flex-1 flex-col">{children}</div>
      {footer}
    </div>
  );
}

const WS_DOT: Record<WsStatus, string> = {
  disconnected: "bg-[var(--danger)]",
  connecting: "bg-[var(--ember)] animate-pulse",
  connected: "bg-[var(--success)]",
  error: "bg-[var(--danger)]",
};

export function ContextBar({
  title,
  turnCount,
  wsStatus,
  onExit,
}: {
  title: string;
  turnCount?: number;
  wsStatus: WsStatus;
  onExit: () => void;
}) {
  return (
    <header className="flex shrink-0 items-center gap-3 border-b border-[var(--line)] px-4 py-3 [font-family:var(--font-ui)] sm:px-6">
      <button
        type="button"
        onClick={onExit}
        className="shrink-0 text-xs tracking-[0.14em] text-[var(--muted)] uppercase transition hover:text-[var(--ink)]"
      >
        Salir
      </button>
      <h1 className="min-w-0 flex-1 truncate text-sm text-[var(--ink)] [font-family:var(--font-display)]">
        {title}
      </h1>
      <div className="flex shrink-0 items-center gap-2 text-xs text-[var(--muted)]">
        {typeof turnCount === "number" && <span>Turno {turnCount}</span>}
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 rounded-full ${WS_DOT[wsStatus]}`}
        />
        <span className="sr-only">{wsStatusLabel(wsStatus)}</span>
      </div>
    </header>
  );
}

const COMPOSER_HINT_KEY = "dungeon-agent.composerHintSeen";

export function Composer({
  value,
  onChange,
  onSubmit,
  disabled,
  error,
  lockedLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  error?: string | null;
  lockedLabel?: string;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [hintSeen, setHintSeen] = useState(() => {
    try {
      return localStorage.getItem(COMPOSER_HINT_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const lineHeight = 24;
    const maxHeight = lineHeight * 4;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [value]);

  function dismissHint() {
    if (hintSeen) return;
    setHintSeen(true);
    try {
      localStorage.setItem(COMPOSER_HINT_KEY, "1");
    } catch {
      // ignore
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      dismissHint();
      onSubmit();
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        dismissHint();
        onSubmit();
      }}
      className="shrink-0 border-t border-[var(--line)] bg-[var(--surface-1)] px-4 py-3 [font-family:var(--font-ui)] sm:px-6"
    >
      {!hintSeen && (
        <p className="mb-2 text-[0.7rem] tracking-wide text-[var(--muted)]">
          Cmd/Ctrl + Enter para enviar · Enter para nueva línea
        </p>
      )}
      <div className="flex items-end gap-2">
        <label className="min-w-0 flex-1">
          <span className="sr-only">Tu acción</span>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            rows={1}
            placeholder={disabled && lockedLabel ? lockedLabel : "¿Qué haces?"}
            className="max-h-24 min-h-6 w-full resize-none bg-transparent px-1 py-1 text-base leading-6 text-[var(--ink)] outline-none placeholder:text-[var(--muted)]/60 disabled:opacity-50"
          />
        </label>
        <button
          type="submit"
          disabled={disabled || value.trim().length === 0}
          aria-label="Enviar acción"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[var(--ember)]/70 bg-[var(--ember)]/15 text-[var(--ink)] transition disabled:cursor-not-allowed disabled:opacity-30"
        >
          ↵
        </button>
      </div>
      <ErrorLine message={error} />
    </form>
  );
}

export function TranscriptEntry({
  action,
  narration,
  children,
}: {
  action?: string | null;
  narration: string;
  children?: ReactNode;
}) {
  return (
    <article className="border-l border-[var(--line)] pl-4">
      {action && (
        <p className="mb-2 text-sm text-[var(--muted)] [font-family:var(--font-ui)]">
          » {action}
        </p>
      )}
      {children}
      <p className="text-base leading-[1.75] whitespace-pre-wrap text-[var(--ink)]">
        {narration}
      </p>
    </article>
  );
}

export function DiceChip({ roll, success }: { roll: number; success?: boolean }) {
  const color =
    success === true
      ? "text-[var(--success)] border-[var(--success)]/40"
      : success === false
        ? "text-[var(--danger)] border-[var(--danger)]/40"
        : "text-[var(--muted)] border-[var(--line)]";
  return (
    <span
      className={`mb-2 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs tracking-wide [font-family:var(--font-ui)] ${color}`}
    >
      d20 · {roll}
      {typeof success === "boolean" ? ` — ${success ? "éxito" : "fallo"}` : ""}
    </span>
  );
}

export function Card({
  title,
  meta,
  onClick,
  disabled,
  selected,
}: {
  title: string;
  meta?: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  selected?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex w-full flex-col gap-1 border px-4 py-3 text-left transition disabled:cursor-not-allowed disabled:opacity-40 ${
        selected
          ? "border-[var(--ember)] bg-[var(--ember)]/10"
          : "border-[var(--line)] bg-[var(--surface-1)] hover:border-[var(--ember)]/50"
      }`}
    >
      <span className="truncate text-base text-[var(--ink)] [font-family:var(--font-display)]">
        {title}
      </span>
      {meta && (
        <span className="text-xs tracking-wide text-[var(--muted)] uppercase [font-family:var(--font-ui)]">
          {meta}
        </span>
      )}
    </button>
  );
}

export function GhostField({
  id,
  label,
  value,
  onChange,
  minLength,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  minLength?: number;
  placeholder?: string;
}) {
  return (
    <label className="mt-10 flex w-full max-w-xs flex-col gap-2 text-left">
      <span className="text-xs tracking-[0.22em] text-[var(--muted)] uppercase">
        {label}
      </span>
      <input
        id={id}
        value={value}
        minLength={minLength}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="border-0 border-b border-[var(--line)] bg-transparent px-0 py-2 text-[var(--ink)] outline-none placeholder:text-[var(--muted)]/50 focus:border-[var(--ember)]/60"
      />
    </label>
  );
}

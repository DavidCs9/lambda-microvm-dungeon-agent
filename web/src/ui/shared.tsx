import type { ReactNode } from "react";

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
      className="mt-6 max-w-md text-center text-sm leading-relaxed text-[#e8a07a]"
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

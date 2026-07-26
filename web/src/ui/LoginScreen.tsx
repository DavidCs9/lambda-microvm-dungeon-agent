import { motion } from "framer-motion";
import { useState } from "react";
import {
  authErrorMessage,
  signIn,
  type AuthSession,
  type NewPasswordChallenge,
} from "../auth/cognito";
import { EmberButton, ErrorLine, GhostField, QuietMeta, ScreenShell } from "./shared";

export function LoginScreen({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [challenge, setChallenge] = useState<NewPasswordChallenge | null>(null);

  if (challenge) {
    return <NewPasswordScreen challenge={challenge} onAuthenticated={onAuthenticated} />;
  }

  async function submit() {
    if (busy || !email.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      const result = await signIn(email.trim(), password);
      if ("accessToken" in result) {
        onAuthenticated(result);
      } else {
        setChallenge(result);
      }
    } catch (signInError) {
      setError(authErrorMessage(signInError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScreenShell className="text-center">
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
        className="flex w-full flex-col items-center"
      >
        <p
          className="text-[clamp(2.75rem,9vw,5.5rem)] leading-[0.95] tracking-[0.04em] text-[var(--ink)] [font-family:var(--font-display)]"
          style={{ textShadow: "0 0 60px rgba(217, 119, 58, 0.22)" }}
        >
          Dungeon Agent
        </p>
        <p className="mt-6 text-lg text-[var(--muted)]">La mesa espera a sus jugadores.</p>
        <form
          className="mt-4 flex w-full max-w-xs flex-col items-center"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <GhostField
            id="email"
            label="Correo"
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="tu@correo.com"
          />
          <GhostField
            id="password"
            label="Contraseña"
            type="password"
            value={password}
            onChange={setPassword}
          />
          <EmberButton type="submit" disabled={busy || !email.trim() || !password}>
            {busy ? "Entrando…" : "Entrar"}
          </EmberButton>
          <ErrorLine message={error} />
        </form>
        <QuietMeta>Acceso privado · las cuentas las administra el dueño de la demo</QuietMeta>
      </motion.div>
    </ScreenShell>
  );
}

function NewPasswordScreen({
  challenge,
  onAuthenticated,
}: {
  challenge: NewPasswordChallenge;
  onAuthenticated: (session: AuthSession) => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requirements = [
    [password.length >= 12, "Al menos 12 caracteres"],
    [/[a-z]/.test(password), "Una letra minúscula"],
    [/[A-Z]/.test(password), "Una letra mayúscula"],
    [/\d/.test(password), "Un número"],
    [/[^A-Za-z0-9]/.test(password), "Un símbolo"],
  ] as const;
  const valid = requirements.every(([met]) => met) && password === confirmation;

  async function submit() {
    if (busy || !valid) return;
    setBusy(true);
    setError(null);
    try {
      onAuthenticated(await challenge.complete(password));
    } catch (challengeError) {
      setError(authErrorMessage(challengeError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScreenShell className="text-center">
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
        className="flex w-full flex-col items-center"
      >
        <p className="text-5xl leading-none tracking-[0.04em] text-[var(--ink)] [font-family:var(--font-display)]">
          Nueva contraseña
        </p>
        <p className="mt-6 max-w-sm text-lg text-[var(--muted)]">
          Tu contraseña temporal ya fue aceptada. Elige una contraseña permanente para continuar.
        </p>
        <form
          className="mt-4 flex w-full max-w-xs flex-col items-center"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <GhostField
            id="new-password"
            label="Nueva contraseña"
            type="password"
            value={password}
            onChange={setPassword}
          />
          <ul className="mt-2 w-full space-y-1 text-left text-sm text-[var(--muted)]" aria-label="Requisitos de contraseña">
            {requirements.map(([met, label]) => (
              <li key={label} className={met ? "text-[var(--success)]" : undefined}>
                {met ? "✓" : "○"} {label}
              </li>
            ))}
          </ul>
          <GhostField
            id="confirm-password"
            label="Repite la contraseña"
            type="password"
            value={confirmation}
            onChange={setConfirmation}
          />
          {confirmation && password !== confirmation && (
            <p className="mt-2 text-sm text-[var(--danger)]">Las contraseñas no coinciden.</p>
          )}
          <EmberButton type="submit" disabled={busy || !valid}>
            {busy ? "Guardando…" : "Continuar"}
          </EmberButton>
          <ErrorLine message={error} />
        </form>
      </motion.div>
    </ScreenShell>
  );
}

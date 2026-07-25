import { motion } from "framer-motion";
import { useState } from "react";
import { authErrorMessage, signIn, type AuthSession } from "../auth/cognito";
import { EmberButton, ErrorLine, GhostField, QuietMeta, ScreenShell } from "./shared";

export function LoginScreen({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (busy || !email.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      onAuthenticated(await signIn(email.trim(), password));
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

import { motion } from "framer-motion";
import { useState } from "react";
import {
  authErrorMessage,
  completeNewPassword,
  signIn,
  type AuthSession,
  type NewPasswordChallenge,
} from "../auth/cognito";
import { EmberButton, ErrorLine, GhostField, QuietMeta, ScreenShell } from "./shared";

export function LoginScreen({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirmation, setNewPasswordConfirmation] = useState("");
  const [challenge, setChallenge] = useState<NewPasswordChallenge | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (busy) return;
    if (!challenge && (!email.trim() || !password)) return;
    if (challenge && (!newPassword || newPassword !== newPasswordConfirmation)) {
      setError("Las contraseñas nuevas deben coincidir.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (challenge) {
        onAuthenticated(await completeNewPassword(challenge, newPassword));
        return;
      }
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
        <p className="mt-6 text-lg text-[var(--muted)]">
          {challenge ? "Elige tu contraseña permanente." : "La mesa espera a sus jugadores."}
        </p>
        <form
          className="mt-4 flex w-full max-w-xs flex-col items-center"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          {!challenge ? (
            <>
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
                label="Contraseña temporal"
                type="password"
                value={password}
                onChange={setPassword}
              />
            </>
          ) : (
            <>
              <GhostField
                id="new-password"
                label="Nueva contraseña"
                type="password"
                value={newPassword}
                onChange={setNewPassword}
              />
              <GhostField
                id="new-password-confirmation"
                label="Repite la contraseña"
                type="password"
                value={newPasswordConfirmation}
                onChange={setNewPasswordConfirmation}
              />
            </>
          )}
          <EmberButton
            type="submit"
            disabled={
              busy ||
              (!challenge && (!email.trim() || !password)) ||
              (!!challenge && (!newPassword || !newPasswordConfirmation))
            }
          >
            {busy ? "Guardando…" : challenge ? "Guardar contraseña" : "Entrar"}
          </EmberButton>
          <ErrorLine message={error} />
        </form>
        <QuietMeta>Acceso privado · las cuentas las administra el dueño de la demo</QuietMeta>
      </motion.div>
    </ScreenShell>
  );
}

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { currentAuthSession, signOut, type AuthSession } from "./auth/cognito";
import { AtmosphereStage } from "./game/AtmosphereStage";
import { gameActions, useGameStore } from "./state/store";
import { LoginScreen } from "./ui/LoginScreen";
import { MenuScreen } from "./ui/MenuScreen";
import { CampaignsScreen } from "./ui/CampaignsScreen";
import { PhaseTheaterScreen } from "./ui/PhaseTheaterScreen";
import { OpeningScrollScreen } from "./ui/OpeningScrollScreen";
import { PlayTableScreen } from "./ui/PlayTableScreen";
import { OutcomeScreen } from "./ui/OutcomeScreen";

/**
 * Showcase shell for RFC 0003.
 * Screen content and store live in ui/ and state/; Pixi lives in game/.
 */
export function App() {
  const screen = useGameStore((s) => s.screen);
  const diceBeat = useGameStore((s) => s.diceBeat);
  const [authSession, setAuthSession] = useState<AuthSession | null | undefined>(undefined);

  useEffect(() => {
    void currentAuthSession()
      .then((session) => setAuthSession(session))
      .catch(() => setAuthSession(null));
  }, []);

  useEffect(() => {
    if (authSession) {
      gameActions.setPlayerId(authSession.userSub);
    }
  }, [authSession]);

  if (authSession === undefined) {
    return <div className="min-h-screen bg-[var(--deep)]" />;
  }

  if (!authSession) {
    return <LoginScreen onAuthenticated={setAuthSession} />;
  }

  function logout() {
    signOut();
    gameActions.resetToMenu();
    setAuthSession(null);
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-[var(--deep)] text-[var(--ink)]">
      <AtmosphereStage diceBeat={diceBeat} screen={screen} />
      <div className="relative z-10 min-h-screen">
        <button
          type="button"
          onClick={logout}
          className="absolute right-6 top-6 z-20 text-xs tracking-[0.14em] text-[var(--muted)] uppercase transition hover:text-[var(--ink)]"
        >
          Salir
        </button>
        <AnimatePresence mode="wait">
          <motion.div
            key={screen}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.35 }}
            className="min-h-screen"
          >
            {screen === "menu" && <MenuScreen />}
            {screen === "campaigns" && <CampaignsScreen />}
            {screen === "phase" && <PhaseTheaterScreen />}
            {screen === "opening" && <OpeningScrollScreen />}
            {screen === "play" && <PlayTableScreen />}
            {screen === "outcome" && <OutcomeScreen />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

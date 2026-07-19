/** Spanish copy helpers. Never surface raw backend codes/phases in the UI. */

const ERROR_COPY: Record<string, string> = {
  campaign_creation_failed: "El fuego se apagó al forjar. Inténtalo de nuevo.",
  session_creation_failed: "La mesa no pudo prepararse. Inténtalo de nuevo.",
  validation_failed: "Algo en la petición no cuadra. Revisa e inténtalo de nuevo.",
  not_authorized: "No tienes acceso a esa mesa. Verifica tu nombre de jugador.",
  campaign_not_found: "Esa campaña no existe o ya no está disponible.",
  session_not_found: "Esa sesión no existe o ya no está disponible.",
  dependency_unavailable: "El territorio no responde ahora. Inténtalo en un momento.",
  internal_error: "Algo se rompió tras el velo. Inténtalo de nuevo.",
  revision_conflict: "La mesa avanzó mientras escribías. Recarga e inténtalo de nuevo.",
  rate_limited: "Demasiadas invocaciones seguidas. Espera un momento.",
};

export function humanError(code: string | null | undefined): string {
  if (!code) {
    return "Algo falló. Inténtalo de nuevo.";
  }
  const copy = ERROR_COPY[code];
  if (!copy) {
    console.warn(`humanError: unmapped code "${code}"`);
    return "Algo falló. Inténtalo de nuevo.";
  }
  return copy;
}

const CAMPAIGN_PHASE_COPY: Record<string, string> = {
  requested: "Llamando al fuego…",
  creating_adventure: "El territorio toma forma…",
  creating_character: "El territorio toma forma…",
  ready: "Listo",
  failed: "El ritual falló",
};

const SESSION_PHASE_COPY: Record<string, string> = {
  requested: "Preparando la mesa…",
  starting_microvm: "El MicroVM despierta…",
  waiting_for_microvm: "El MicroVM despierta…",
  initializing_game: "Anclando el mundo…",
  ready: "En la mesa",
  playing: "En la mesa",
  rehydrating: "Reanudando…",
  failed: "La sesión falló",
};

export function humanPhase(
  phase: string | null | undefined,
  kind?: "campaign" | "session" | null,
): string {
  if (!phase) {
    return "En marcha…";
  }
  const table = kind === "session" ? SESSION_PHASE_COPY : CAMPAIGN_PHASE_COPY;
  const copy = table[phase] ?? CAMPAIGN_PHASE_COPY[phase] ?? SESSION_PHASE_COPY[phase];
  if (!copy) {
    console.warn(`humanPhase: unmapped phase "${phase}"`);
    return "En marcha…";
  }
  return copy;
}

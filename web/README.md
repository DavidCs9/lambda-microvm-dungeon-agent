# Dungeon Agent — showcase client (RFC 0003)

Cliente browser de demostración: atmósfera Pixi, ritual de campaña en español,
apertura en scroll, mesa de juego y beat de dados. Habla con el control plane
sandbox vía HTTP + WebSocket (`x-player-id`).

## Setup

```bash
cd web
cp .env.example .env.local
```

Rellena `.env.local` con los outputs del stack sandbox (`ApiUrl`, `WebSocketUrl`):

```bash
aws cloudformation describe-stacks \
  --stack-name dungeon-agent-control-plane-sandbox \
  --region us-east-2 \
  --query 'Stacks[0].Outputs'
```

```bash
npm install
npm run dev
```

Abre la URL local. Pon un `playerId` (mín. 3 caracteres) y pulsa **Empezar**.

## Layout

```text
src/
  game/   Pixi atmosphere + dice + Web Audio
  ui/     React screens (landing → ritual → phase → opening → play → outcome)
  net/    HTTP + WebSocket adapters
  state/  Event-driven store (useSyncExternalStore)
  debug/  Lab v0 console (fallback)
```

Consola operador (JSON): abre `debug.html` en Vite (`/debug.html`).

Auth sandbox: `x-player-id` / `playerId`. Sin Cognito. Idioma oficial de demo: `es`.

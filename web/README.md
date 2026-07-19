# Cliente web v0 (laboratorio)

Página mínima Vite + TypeScript contra el control plane sandbox. El idioma oficial
de juego es **español** (`language: "es"` en create campaign/session).

1. Conectar WebSocket con `playerId`
2. Crear una campaña y ver las fases
3. Crear una sesión contra esa campaña
4. Enviar una acción y ver eventos

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

Instala y arranca:

```bash
npm install
npm run dev
```

Abre la URL local. Pon un `playerId` (mín. 3 caracteres; se guarda en `localStorage`),
pulsa **Conectar WebSocket** y luego **Crear campaña**.

Auth sandbox: cada request HTTP manda `x-player-id`. Sin Cognito en v0.

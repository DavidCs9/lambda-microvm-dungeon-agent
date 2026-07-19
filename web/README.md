# Lab v0 browser client

Minimal Vite + TypeScript page that drives the sandbox control plane:

1. Connect WebSocket with `playerId`
2. Create a campaign and watch phases
3. Create a session against that campaign
4. Submit an action and dump events

## Setup

```bash
cd web
cp .env.example .env.local
```

Fill `.env.local` from the sandbox stack outputs (`ApiUrl`, `WebSocketUrl`):

```bash
aws cloudformation describe-stacks \
  --stack-name dungeon-agent-control-plane-sandbox \
  --region us-east-2 \
  --query 'Stacks[0].Outputs'
```

Install and run:

```bash
npm install
npm run dev
```

Open the printed local URL. Set a `playerId` (min 3 chars; stored in `localStorage`), click **Connect WebSocket**, then **Create Campaign**.

Auth is sandbox-only: every HTTP call sends `x-player-id`. No Cognito in v0.

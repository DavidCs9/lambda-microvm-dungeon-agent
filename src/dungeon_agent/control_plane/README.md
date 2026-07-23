# Planes

Lab packaging for **control plane** vs **data plane**. One SAM deploy; two packages.

| Package | Owns |
|---|---|
| `control_plane/` | Campaign + session **lifecycle**: create, list, get, abandon, Step Functions workflows, adventure/character/portrait agents |
| `data_plane/` | **Live play**: `POST …/actions`, turn worker, `POST /speech`, session event replay, Dungeon Master agent |
| `plane_shared/` | Contracts, DynamoDB, WebSocket transport/delivery, MicroVM manager, HTTP API adapter (`ROUTE_PLANE`) |

Lambda handlers remain `dungeon_agent.control_plane.runtime.*` so the SAM template does not churn.

See [architecture.md](../../docs/architecture.md) for C4 L1–L3 and the full endpoint tables.

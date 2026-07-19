# RFC 0002 — Lo que falta (Lab Edition)

## Mindset

Lee `AGENTS.md` primero. Esto es un **laboratorio personal**, no enterprise.

- Lo que existe se queda (RFCs, docs, contratos). No se borra nada.
- Lo que **falta** se hace simple y directo. Sin slices, sin fases, sin alarmas extra.
- Un solo dev: David. Branch → commit → push → PR. Él mergea del móvil.

---

## Estado actual: ~80%

Las 5 capas de código ya están implementadas. Falta solo **1 pieza de infra**.

### ✅ Ya existe (no tocar)

| Capa | Archivos clave |
|------|---------------|
| Contratos (CampaignId, eventos, errores) | `domain/enums.py`, `domain/models.py`, `domain/lifecycle.py` |
| Persistencia campañas | `persistence/memory.py`, `persistence/dynamodb_campaigns.py` |
| Workflow de campaña | `workflow/campaigns.py` (317 lines — `DurableCampaignWorkflowStub`) |
| Fork de campaña en sesión | `workflow/stub.py` (`_fork_campaign`) |
| HTTP handlers | `http/handlers.py` (`POST/GET /campaigns`) |
| WebSocket para campañas | `realtime/service.py` (`subscribe_campaign`) |
| Tests | `tests/test_control_plane_campaigns.py`, `tests/test_control_plane_campaign_workflow.py` |
| CampaignTable + rutas API | `infra/control-plane/workflow/template.yaml` (líneas 60-70, 166-184) |

### ❌ Lo único que falta

En `infra/control-plane/workflow/template.yaml`:

**`CreateCampaignStateMachine` no está definida.** Existe `CreateSessionStateMachine` (línea 349), pero la de campaña solo se referencia via `!GetAtt` (líneas 118, 129) sin definición.

**Qué incluir (mínimo viable, sin alarmas extra):**

1. **`CreateCampaignWorkflowLogGroup`** — log group para la state machine
2. **`CreateCampaignStateMachineRole`** — IAM role con permisos para invocar `WorkflowTaskFunction` y escribir en `CampaignTable`
3. **`CreateCampaignStateMachine`** — Standard state machine con los steps:
   - ValidateSession → CreateCampaignRecord → GenerateAdventure → GenerateCharacter → MarkCampaignReady
   - Mismo patrón que `CreateSessionStateMachine` (mismas retry/catch policies)
4. **Output `CampaignTableName`** — para consultar desde fuera

**No incluir** (lab mindset):
- ❌ Alarmas CloudWatch separadas para campaña (si falla, lo ves en los logs)
- ❌ Terminal event rule para campaña (el monitor actual solo cubre session)
- ❌ Roles IAM ultra-segmentados (un solo role de state machine basta)

### Resumen

```
1 archivo, ~100 líneas de YAML, ~2 horas.
```
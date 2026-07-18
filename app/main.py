from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request

from app.config import Settings, get_settings
from app.models import ActionRequest, HealthResponse, WorldState
from app.state_store import StateStore


def get_store(request: Request) -> StateStore:
    return request.app.state.store  # type: ignore[no-any-return]


StoreDependency = Annotated[StateStore, Depends(get_store)]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = StateStore(resolved_settings.workspace_dir)
        await store.initialize()
        app.state.store = store
        yield

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Backend API for the Lambda MicroVM Dungeon Agent lab.",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/v1/world", response_model=WorldState, tags=["world"])
    async def read_world(store: StoreDependency) -> WorldState:
        return await store.read()

    @app.post("/v1/actions", response_model=WorldState, tags=["world"])
    async def apply_action(
        payload: ActionRequest,
        store: StoreDependency,
    ) -> WorldState:
        return await store.apply_action(payload.action)

    return app


app = create_app()

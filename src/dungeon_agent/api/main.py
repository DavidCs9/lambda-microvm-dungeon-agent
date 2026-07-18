from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request

from dungeon_agent.api.config import Settings, get_settings
from dungeon_agent.api.models import (
    AdventureRequest,
    HealthResponse,
    LanguageRequest,
    TurnRequest,
    WorldState,
)
from dungeon_agent.api.state_store import StateStore


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

    @app.put("/v1/language", response_model=WorldState, tags=["world"])
    async def set_language(payload: LanguageRequest, store: StoreDependency) -> WorldState:
        return await store.set_language(payload.language)

    @app.put("/v1/adventure", response_model=WorldState, tags=["world"])
    async def start_adventure(
        payload: AdventureRequest,
        store: StoreDependency,
    ) -> WorldState:
        return await store.start_adventure(payload.language, payload.plan)

    @app.post("/v1/turns", response_model=WorldState, tags=["world"])
    async def apply_turn(payload: TurnRequest, store: StoreDependency) -> WorldState:
        try:
            return await store.apply_turn(payload.action, payload.proposal)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return app


app = create_app()

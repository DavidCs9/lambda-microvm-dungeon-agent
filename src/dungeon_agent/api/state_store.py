import asyncio
import json
import os
from pathlib import Path

from dungeon_agent.api.adventure import initial_world, resolve_turn, start_adventure
from dungeon_agent.api.models import AdventurePlan, LanguageCode, TurnProposal, WorldState


class StateStore:
    """Persist one MicroVM session's world using atomic file replacement."""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir
        self.state_path = workspace_dir / "world.json"
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self._write(initial_world())

    async def read(self) -> WorldState:
        async with self._lock:
            return self._read()

    async def set_language(self, language: LanguageCode) -> WorldState:
        async with self._lock:
            current = self._read()
            updated = (
                initial_world(language)
                if current.status == "planning"
                else current.model_copy(update={"language": language})
            )
            self._write(updated)
            return updated

    async def start_adventure(self, language: LanguageCode, plan: AdventurePlan) -> WorldState:
        async with self._lock:
            updated = start_adventure(language, plan)
            self._write(updated)
            return updated

    async def apply_turn(self, action: str, proposal: TurnProposal) -> WorldState:
        async with self._lock:
            updated = resolve_turn(self._read(), action, proposal)
            self._write(updated)
            return updated

    def _read(self) -> WorldState:
        return WorldState.model_validate_json(self.state_path.read_text(encoding="utf-8"))

    def _write(self, world: WorldState) -> None:
        temporary_path = self.state_path.with_suffix(".json.tmp")
        serialized = json.dumps(world.model_dump(mode="json"), indent=2) + "\n"
        temporary_path.write_text(serialized, encoding="utf-8")
        os.chmod(temporary_path, 0o600)
        temporary_path.replace(self.state_path)

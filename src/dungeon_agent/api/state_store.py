import asyncio
import json
import os
from pathlib import Path

from dungeon_agent.api.adventure import initial_world, resolve_action
from dungeon_agent.api.models import LanguageCode, WorldState


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
                if current.revision == 0
                else current.model_copy(update={"language": language})
            )
            self._write(updated)
            return updated

    async def apply_action(self, action: str) -> WorldState:
        async with self._lock:
            current = self._read()
            updated = resolve_action(current, action)
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

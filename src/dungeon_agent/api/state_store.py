import asyncio
import json
import os
from pathlib import Path

from dungeon_agent.api.models import WorldState

INITIAL_WORLD = WorldState(
    revision=0,
    location="The Snapshot Tavern",
    inventory=[],
    story=["You awaken beside a humming Firecracker."],
)


class StateStore:
    """Persist one MicroVM session's world using atomic file replacement."""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir
        self.state_path = workspace_dir / "world.json"
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self._write(INITIAL_WORLD.model_copy(deep=True))

    async def read(self) -> WorldState:
        async with self._lock:
            return self._read()

    async def apply_action(self, action: str) -> WorldState:
        async with self._lock:
            current = self._read()
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "story": [*current.story, action],
                }
            )
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

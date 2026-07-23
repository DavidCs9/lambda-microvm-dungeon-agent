"""Compatibility imports for the local orchestrator."""

from dungeon_agent.control_plane.agents.bedrock import StructuredBedrockAgent
from dungeon_agent.control_plane.agents.roles import (
    AdventureArchitect,
    CharacterArchitect,
    DungeonMaster,
)

__all__ = [
    "AdventureArchitect",
    "CharacterArchitect",
    "DungeonMaster",
    "StructuredBedrockAgent",
]

"""Compatibility imports for the local orchestrator."""

from dungeon_agent.control_plane.agents.roles import AdventureArchitect, CharacterArchitect
from dungeon_agent.data_plane.agents.roles import DungeonMaster
from dungeon_agent.plane_shared.agents.bedrock import StructuredBedrockAgent

__all__ = [
    "AdventureArchitect",
    "CharacterArchitect",
    "DungeonMaster",
    "StructuredBedrockAgent",
]

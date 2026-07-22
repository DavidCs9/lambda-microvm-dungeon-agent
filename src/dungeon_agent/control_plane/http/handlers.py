"""Backward-compatible HTTP handler exports."""

from dungeon_agent.control_plane.http.campaigns import CampaignHttpHandlers
from dungeon_agent.control_plane.http.sessions import SessionHttpHandlers
from dungeon_agent.control_plane.http.speech import SpeechHttpHandlers

__all__ = [
    "CampaignHttpHandlers",
    "SessionHttpHandlers",
    "SpeechHttpHandlers",
]

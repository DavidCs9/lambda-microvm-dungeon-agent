"""Session creation independent of HTTP and AWS transports."""

from collections.abc import Callable
from datetime import datetime

from dungeon_agent.control_plane.domain.enums import SessionPhase, SessionStatus
from dungeon_agent.control_plane.domain.models import (
    CreateSessionCommand,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.identifiers import new_session_id


class DefaultSessionFactory:
    def __init__(self, id_factory: Callable[[], SessionId] = new_session_id) -> None:
        self._id_factory = id_factory

    def create(self, command: CreateSessionCommand, now: datetime) -> SessionRecord:
        return SessionRecord(
            session_id=self._id_factory(),
            owner_id=command.owner_id,
            language=command.language,
            status=SessionStatus.REQUESTED,
            phase=SessionPhase.REQUESTED,
            revision=0,
            last_event_sequence=0,
            created_at=now,
            updated_at=now,
            campaign_id=command.campaign_id,
            campaign_revision=command.campaign_revision,
        )

"""Application ports implemented by later parallel workstreams."""

from datetime import datetime
from typing import Protocol

from dungeon_agent.control_plane.domain.models import (
    CreateSessionCommand,
    CreateSessionWorkflowInput,
    MicrovmLaunchResult,
    OpeningDocument,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter, WorldState


class SessionRepository(Protocol):
    def create(self, session: SessionRecord, idempotency_key: str) -> SessionRecord: ...

    def get(self, session_id: SessionId) -> SessionRecord | None: ...

    def find_by_idempotency_key(
        self, owner_id: str, idempotency_key: str
    ) -> SessionRecord | None: ...

    def save(self, session: SessionRecord, *, expected_revision: int) -> SessionRecord: ...


class EventRepository(Protocol):
    def append(self, event: SessionEvent, *, expected_previous_sequence: int) -> None: ...

    def list_after(self, session_id: SessionId, sequence: int) -> tuple[SessionEvent, ...]: ...


class AdventureArchitectPort(Protocol):
    def create(self, language: LanguageCode) -> AdventurePlan: ...


class CharacterArchitectPort(Protocol):
    def create(self, language: LanguageCode, adventure: AdventurePlan) -> PlayerCharacter: ...


class MicrovmManagerPort(Protocol):
    def launch(self, session_id: SessionId) -> MicrovmLaunchResult: ...

    def initialize(
        self,
        microvm_id: str,
        language: LanguageCode,
        adventure: AdventurePlan,
        character: PlayerCharacter,
    ) -> WorldState: ...

    def rehydrate(self, session_id: SessionId, state: WorldState) -> MicrovmLaunchResult: ...

    def terminate(self, microvm_id: str) -> None: ...


class EventDeliveryPort(Protocol):
    def deliver(self, owner_id: str, event: SessionEvent) -> None: ...


class WorkflowStarterPort(Protocol):
    def start_create_session(self, workflow_input: CreateSessionWorkflowInput) -> str: ...


class SessionFactoryPort(Protocol):
    def create(self, command: CreateSessionCommand, now: datetime) -> SessionRecord: ...


class OpeningBuilderPort(Protocol):
    def build(
        self, language: LanguageCode, adventure: AdventurePlan, character: PlayerCharacter
    ) -> OpeningDocument: ...

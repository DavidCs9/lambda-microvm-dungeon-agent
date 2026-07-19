"""Application ports implemented by later parallel workstreams."""

from datetime import datetime
from typing import Protocol

from dungeon_agent.control_plane.domain.models import (
    CampaignEvent,
    CampaignId,
    CampaignRecord,
    CreateCampaignCommand,
    CreateCampaignWorkflowInput,
    CreateSessionCommand,
    CreateSessionWorkflowInput,
    MicrovmLaunchResult,
    OpeningDocument,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.domain.game import (
    AdventurePlan,
    LanguageCode,
    PlayerCharacter,
    TurnProposal,
    WorldState,
)


class SessionRepository(Protocol):
    def create(self, session: SessionRecord, idempotency_key: str) -> SessionRecord: ...

    def get(self, session_id: SessionId) -> SessionRecord | None: ...

    def find_by_idempotency_key(
        self, owner_id: str, idempotency_key: str
    ) -> SessionRecord | None: ...

    def save(self, session: SessionRecord, *, expected_revision: int) -> SessionRecord: ...

    def count_active_by_owner(self, owner_id: str) -> int: ...

    def count_by_campaign(self, campaign_id: CampaignId) -> int: ...


class CampaignRepository(Protocol):
    def create(self, campaign: CampaignRecord, idempotency_key: str) -> CampaignRecord: ...

    def get(self, campaign_id: CampaignId) -> CampaignRecord | None: ...

    def find_by_idempotency_key(
        self, owner_id: str, idempotency_key: str
    ) -> CampaignRecord | None: ...

    def save(self, campaign: CampaignRecord, *, expected_revision: int) -> CampaignRecord: ...

    def count_by_owner(self, owner_id: str) -> int: ...

    def list_by_owner(
        self, owner_id: str, *, status: str | None = None
    ) -> tuple[CampaignRecord, ...]: ...


class EventRepository(Protocol):
    def append(self, event: SessionEvent, *, expected_previous_sequence: int) -> None: ...

    def list_after(self, session_id: SessionId, sequence: int) -> tuple[SessionEvent, ...]: ...


class CampaignEventRepository(Protocol):
    def append(self, event: CampaignEvent, *, expected_previous_sequence: int) -> None: ...

    def list_after(self, campaign_id: CampaignId, sequence: int) -> tuple[CampaignEvent, ...]: ...


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

    def apply_turn(self, microvm_id: str, action: str, proposal: TurnProposal) -> WorldState: ...

    def is_running(self, microvm_id: str) -> bool: ...

    def rehydrate(self, session_id: SessionId, state: WorldState) -> MicrovmLaunchResult: ...

    def terminate(self, microvm_id: str) -> None: ...


class EventDeliveryPort(Protocol):
    def deliver(self, owner_id: str, event: SessionEvent) -> None: ...


class CampaignEventDeliveryPort(Protocol):
    def deliver_campaign(self, owner_id: str, event: CampaignEvent) -> None: ...


class WorkflowStarterPort(Protocol):
    def start_create_session(self, workflow_input: CreateSessionWorkflowInput) -> str: ...

    def start_create_campaign(self, workflow_input: CreateCampaignWorkflowInput) -> str: ...


class SessionFactoryPort(Protocol):
    def create(self, command: CreateSessionCommand, now: datetime) -> SessionRecord: ...


class CampaignFactoryPort(Protocol):
    def create(self, command: CreateCampaignCommand, now: datetime) -> CampaignRecord: ...


class OpeningBuilderPort(Protocol):
    def build(
        self, language: LanguageCode, adventure: AdventurePlan, character: PlayerCharacter
    ) -> OpeningDocument: ...

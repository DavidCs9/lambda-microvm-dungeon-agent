import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dungeon_agent.control_plane.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    EventType,
    OpeningBlockKind,
)
from dungeon_agent.control_plane.domain.models import (
    CampaignCreationStartedPayload,
    CampaignEvent,
    CampaignId,
    CampaignRecord,
    OpeningBlock,
    OpeningDocument,
)
from dungeon_agent.control_plane.identifiers import new_campaign_id
from dungeon_agent.control_plane.persistence.errors import (
    CampaignAlreadyExistsError,
    CampaignEventSequenceConflictError,
    CampaignRevisionConflictError,
)
from dungeon_agent.control_plane.persistence.memory import InMemoryCampaignRepository
from dungeon_agent.control_plane.workflow.campaigns import DurableCampaignWorkflowStub

NOW = datetime(2026, 7, 18, 21, 0, tzinfo=UTC)
CAMPAIGN_ID: CampaignId = "cam_01J00000000000000000000000"
ADVENTURE_REF = f"dynamodb://CAMPAIGN#{CAMPAIGN_ID}/ARTIFACT#ADVENTURE"
CHARACTER_REF = f"dynamodb://CAMPAIGN#{CAMPAIGN_ID}/ARTIFACT#CHARACTER"


def make_campaign(
    *,
    campaign_id: CampaignId = CAMPAIGN_ID,
    status: CampaignStatus = CampaignStatus.REQUESTED,
    phase: CampaignPhase = CampaignPhase.REQUESTED,
    revision: int = 0,
) -> CampaignRecord:
    return CampaignRecord(
        campaign_id=campaign_id,
        owner_id="user_demo",
        language="en",
        status=status,
        phase=phase,
        revision=revision,
        last_event_sequence=0,
        created_at=NOW,
        updated_at=NOW,
    )


def test_campaign_ids_use_the_crockford_sortable_format() -> None:
    first, second = new_campaign_id(), new_campaign_id()

    assert first.startswith("cam_") and len(first) == 30
    assert second.startswith("cam_") and len(second) == 30
    assert first != second


def test_ready_campaign_requires_persisted_artifacts() -> None:
    with pytest.raises(ValidationError, match="persisted adventure and character"):
        CampaignRecord(
            campaign_id=CAMPAIGN_ID,
            owner_id="user_demo",
            language="en",
            status=CampaignStatus.READY,
            phase=CampaignPhase.READY,
            revision=3,
            last_event_sequence=4,
            created_at=NOW,
            updated_at=NOW,
        )


def test_campaign_status_requires_the_matching_phase() -> None:
    with pytest.raises(ValidationError, match="requires phase"):
        make_campaign(status=CampaignStatus.FAILED, phase=CampaignPhase.CREATING_ADVENTURE)


def test_campaign_event_validates_payload_and_round_trips() -> None:
    event = CampaignEvent(
        event_id="evt_01J00000000000000000000001",
        campaign_id=CAMPAIGN_ID,
        sequence=1,
        type=EventType.CAMPAIGN_CREATION_STARTED,
        occurred_at=NOW,
        correlation_id="corr-campaign-test",
        payload=CampaignCreationStartedPayload(language="en"),
    )

    serialized = event.model_dump_json(by_alias=True)
    assert CampaignEvent.model_validate_json(serialized) == event
    assert '"campaignId"' in serialized

    with pytest.raises(ValidationError, match="is not a campaign event"):
        CampaignEvent(
            event_id="evt_01J00000000000000000000002",
            campaign_id=CAMPAIGN_ID,
            sequence=2,
            type=EventType.SESSION_READY,
            occurred_at=NOW,
            correlation_id="corr-campaign-test",
            payload=CampaignCreationStartedPayload(language="en"),
        )


def test_in_memory_campaign_create_is_owner_scoped_and_idempotent() -> None:
    repository = InMemoryCampaignRepository()
    first = make_campaign()
    duplicate = make_campaign(campaign_id="cam_01J00000000000000000000009")

    assert repository.create(first, "create-request-001") == first
    assert repository.create(duplicate, "create-request-001") == first
    assert repository.find_by_idempotency_key("user_demo", "create-request-001") == first
    assert repository.find_by_idempotency_key("other_user", "create-request-001") is None
    with pytest.raises(CampaignAlreadyExistsError):
        repository.create(first, "create-request-002")


def test_in_memory_campaign_save_requires_and_advances_exact_revision() -> None:
    repository = InMemoryCampaignRepository()
    original = repository.create(make_campaign(), "create-request-001")
    updated = original.model_copy(update={"revision": 1, "updated_at": NOW + timedelta(seconds=1)})

    assert repository.save(updated, expected_revision=0).revision == 1
    with pytest.raises(CampaignRevisionConflictError):
        repository.save(updated, expected_revision=0)
    with pytest.raises(CampaignRevisionConflictError):
        repository.save(updated.model_copy(update={"revision": 3}), expected_revision=1)


def test_in_memory_campaign_events_are_monotonic_and_replayable() -> None:
    repository = InMemoryCampaignRepository()
    repository.create(make_campaign(), "create-request-001")
    first = _campaign_event(1, suffix="1")
    second = _campaign_event(2, suffix="2")

    repository.append(first, expected_previous_sequence=0)
    repository.append(second, expected_previous_sequence=1)

    stored = repository.get(CAMPAIGN_ID)
    assert stored is not None
    assert stored.last_event_sequence == 2
    assert repository.list_after(CAMPAIGN_ID, 0) == (first, second)
    assert repository.list_after(CAMPAIGN_ID, 1) == (second,)
    with pytest.raises(CampaignEventSequenceConflictError):
        repository.append(_campaign_event(3, suffix="3"), expected_previous_sequence=0)


def test_in_memory_campaign_count_by_owner() -> None:
    repository = InMemoryCampaignRepository()
    repository.create(make_campaign(), "create-request-001")
    repository.create(
        make_campaign(campaign_id="cam_01J00000000000000000000009").model_copy(
            update={"owner_id": "other_user"}
        ),
        "create-request-002",
    )

    assert repository.count_by_owner("user_demo") == 1
    assert repository.count_by_owner("other_user") == 1
    assert repository.count_by_owner("user_nobody") == 0


def test_in_memory_list_by_owner_is_owner_scoped() -> None:
    repository = InMemoryCampaignRepository()
    mine = make_campaign()
    theirs = make_campaign(campaign_id="cam_01J00000000000000000000009").model_copy(
        update={"owner_id": "other_user"}
    )
    repository.create(mine, "create-request-001")
    repository.create(theirs, "create-request-002")

    listed = repository.list_by_owner("user_demo")
    assert [campaign.campaign_id for campaign in listed] == [mine.campaign_id]


def test_in_memory_list_by_owner_filters_status_and_orders_newest_first() -> None:
    repository = InMemoryCampaignRepository()
    older = make_campaign(campaign_id="cam_01J00000000000000000000001")
    newer = make_campaign(campaign_id="cam_01J00000000000000000000002").model_copy(
        update={
            "created_at": NOW + timedelta(seconds=30),
            "updated_at": NOW + timedelta(seconds=30),
            "status": CampaignStatus.READY,
            "phase": CampaignPhase.READY,
            "adventure_ref": ADVENTURE_REF,
            "character_ref": CHARACTER_REF,
        }
    )
    repository.create(older, "create-request-001")
    repository.create(newer, "create-request-002")

    listed = repository.list_by_owner("user_demo")
    assert [campaign.campaign_id for campaign in listed] == [
        newer.campaign_id,
        older.campaign_id,
    ]
    ready_only = repository.list_by_owner("user_demo", status="ready")
    assert [campaign.campaign_id for campaign in ready_only] == [newer.campaign_id]


def test_campaign_record_round_trips_opening_title() -> None:
    campaign = make_campaign().model_copy(update={"opening_title": "The silent tower"})

    serialized = campaign.model_dump_json(by_alias=True)
    assert '"openingTitle":"The silent tower"' in serialized
    restored = CampaignRecord.model_validate_json(serialized)
    assert restored == campaign
    assert restored.opening_title == "The silent tower"

    repository = InMemoryCampaignRepository()
    repository.create(campaign, "create-request-001")
    assert repository.get(campaign.campaign_id).opening_title == "The silent tower"  # type: ignore[union-attr]


def test_campaign_record_without_opening_title_key_defaults_to_none() -> None:
    payload = {
        "campaignId": CAMPAIGN_ID,
        "ownerId": "user_demo",
        "language": "en",
        "status": "requested",
        "phase": "requested",
        "revision": 0,
        "lastEventSequence": 0,
        "createdAt": NOW.isoformat(),
        "updatedAt": NOW.isoformat(),
    }

    campaign = CampaignRecord.model_validate_json(json.dumps(payload))

    assert campaign.opening_title is None


def test_mark_campaign_ready_persists_opening_title() -> None:
    repository = InMemoryCampaignRepository()
    campaign = make_campaign()
    repository.create(campaign, "create-request-001")
    opening = _opening(campaign.language)
    stub = DurableCampaignWorkflowStub(repository, openings=_OpeningLoader(opening))

    result = stub.handle(
        {
            "operation": "MarkCampaignReady",
            "workflowExecutionArn": "arn:aws:states:us-east-1:123456789012:execution:campaign:t1",
            "stateEnteredAt": "2026-07-18T21:00:00Z",
            "state": {
                "campaignId": CAMPAIGN_ID,
                "correlationId": "corr-campaign-ready",
                "adventureRef": ADVENTURE_REF,
                "characterRef": CHARACTER_REF,
            },
        }
    )

    saved = repository.get(CAMPAIGN_ID)
    assert saved is not None
    assert saved.opening_title == opening.title
    assert result["status"] == CampaignStatus.READY.value
    stashed = result["opening"]
    assert isinstance(stashed, dict)
    assert stashed["title"] == opening.title


def test_emit_campaign_ready_reuses_stashed_opening() -> None:
    repository = InMemoryCampaignRepository()
    campaign = CampaignRecord(
        campaign_id=CAMPAIGN_ID,
        owner_id="user_demo",
        language="en",
        status=CampaignStatus.READY,
        phase=CampaignPhase.READY,
        revision=1,
        last_event_sequence=0,
        created_at=NOW,
        updated_at=NOW,
        adventure_ref=ADVENTURE_REF,
        character_ref=CHARACTER_REF,
        opening_title="Stashed title",
    )
    repository.create(campaign, "create-request-001")

    class CountingLoader:
        calls = 0

        def load_opening(self, character_ref: str) -> OpeningDocument:
            self.calls += 1
            return _opening("en")

    loader = CountingLoader()
    stub = DurableCampaignWorkflowStub(repository, openings=loader)
    opening = _opening("en").model_copy(update={"title": "Stashed title"})

    stub.handle(
        {
            "operation": "EmitCampaignReady",
            "workflowExecutionArn": "arn:aws:states:us-east-1:123456789012:execution:campaign:t1",
            "stateEnteredAt": "2026-07-18T21:00:00Z",
            "state": {
                "campaignId": CAMPAIGN_ID,
                "correlationId": "corr-campaign-ready",
                "characterRef": CHARACTER_REF,
                "opening": opening.model_dump(by_alias=True),
            },
        }
    )

    assert loader.calls == 0
    events = repository.list_after(CAMPAIGN_ID, 0)
    assert events[-1].payload.opening.title == "Stashed title"


class _OpeningLoader:
    def __init__(self, opening: OpeningDocument) -> None:
        self._opening = opening

    def load_opening(self, character_ref: str) -> OpeningDocument:
        assert character_ref
        return self._opening


def _opening(language: str) -> OpeningDocument:
    blocks = (
        ("identity", OpeningBlockKind.IDENTITY, "You are Elia.", True),
        ("motivation", OpeningBlockKind.MOTIVATION, "You seek your brother.", True),
        ("knowledge_1", OpeningBlockKind.KNOWLEDGE, "The bell vanished.", True),
        ("knowledge_2", OpeningBlockKind.KNOWLEDGE, "Mara saw lights.", True),
        ("situation", OpeningBlockKind.SITUATION, "The tower is silent.", True),
        ("action_1", OpeningBlockKind.POSSIBLE_ACTION, "Inspect the tower.", False),
        ("action_2", OpeningBlockKind.POSSIBLE_ACTION, "Question Mara.", False),
        ("action_3", OpeningBlockKind.POSSIBLE_ACTION, "Cross to the mill.", False),
    )
    return OpeningDocument(
        language=language,
        title="The silent tower",
        blocks=tuple(
            OpeningBlock(id=block_id, position=index, kind=kind, text=text, narratable=narratable)
            for index, (block_id, kind, text, narratable) in enumerate(blocks)
        ),
    )


def _campaign_event(sequence: int, *, suffix: str) -> CampaignEvent:
    return CampaignEvent(
        event_id=f"evt_01J0000000000000000000000{suffix}",
        campaign_id=CAMPAIGN_ID,
        sequence=sequence,
        type=EventType.CAMPAIGN_CREATION_STARTED,
        occurred_at=NOW + timedelta(seconds=sequence),
        correlation_id="corr-campaign-test",
        payload=CampaignCreationStartedPayload(language="en"),
    )

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from dungeon_agent.api import models as api_models
from dungeon_agent.plane_shared.domain.enums import (
    EventType,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.plane_shared.domain.models import (
    CreateSessionWorkflowInput,
    PhaseChangedPayload,
    SessionEvent,
    SessionReadyPayload,
    SessionRecord,
    SubmitTurnCommand,
)
from dungeon_agent.domain.game import AdventurePlan
from dungeon_agent.domain.views import OpeningView

FIXTURES = Path(__file__).parent / "fixtures" / "control_plane"
DOMAIN_ROOTS = (
    Path(__file__).parents[1] / "src" / "dungeon_agent" / "domain",
    Path(__file__).parents[1] / "src" / "dungeon_agent" / "control_plane" / "domain",
)
FORBIDDEN_TOP_LEVEL = {"boto3", "botocore", "fastapi", "textual", "aws_cdk"}
FORBIDDEN_INTERNAL = (
    "dungeon_agent.api",
    "dungeon_agent.audio",
    "dungeon_agent.microvm",
    "dungeon_agent.operations",
    "dungeon_agent.orchestrator",
    "dungeon_agent.tui",
)


@pytest.mark.parametrize("language", ["en", "es"])
def test_bilingual_contract_fixtures_round_trip_deterministically(language: str) -> None:
    document = json.loads((FIXTURES / f"{language}_session.json").read_text(encoding="utf-8"))

    workflow = CreateSessionWorkflowInput.model_validate(document["workflow"])
    session = SessionRecord.model_validate(document["session"])
    event = SessionEvent.model_validate(document["readyEvent"])

    assert workflow.language == language
    assert session.language == language
    assert event.type is EventType.SESSION_READY
    assert isinstance(event.payload, SessionReadyPayload)
    assert event.payload.opening.language == language
    first = event.model_dump_json(by_alias=True)
    assert first == SessionEvent.model_validate_json(first).model_dump_json(by_alias=True)
    assert '"sessionId"' in first
    assert '"occurredAt"' in first


def test_event_type_rejects_the_wrong_payload() -> None:
    with pytest.raises(ValidationError, match="requires payload"):
        SessionEvent(
            event_id="evt_01J00000000000000000000004",
            session_id="ses_01J00000000000000000000000",
            sequence=1,
            type=EventType.SESSION_READY,
            occurred_at=datetime.now(UTC),
            correlation_id="corr-wrong-payload",
            payload=PhaseChangedPayload(phase=SessionPhase.STARTING_MICROVM, elapsed_ms=10),
        )


def test_session_event_rejects_campaign_event_types() -> None:
    with pytest.raises(ValidationError, match="is not a session event"):
        SessionEvent(
            event_id="evt_01J00000000000000000000004",
            session_id="ses_01J00000000000000000000000",
            sequence=1,
            type=EventType.CAMPAIGN_READY,
            occurred_at=datetime.now(UTC),
            correlation_id="corr-wrong-family",
            payload=PhaseChangedPayload(phase=SessionPhase.READY, elapsed_ms=10),
        )


def test_session_lifecycle_requires_a_microvm_when_ready() -> None:
    with pytest.raises(ValidationError, match="require an active MicroVM"):
        SessionRecord(
            session_id="ses_01J00000000000000000000000",
            owner_id="user_demo",
            language="en",
            status=SessionStatus.READY,
            phase=SessionPhase.READY,
            revision=0,
            last_event_sequence=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )


def test_workflow_timestamps_require_a_timezone() -> None:
    with pytest.raises(ValidationError, match="must include a timezone"):
        CreateSessionWorkflowInput(
            session_id="ses_01J00000000000000000000000",
            owner_id="user_demo",
            language="en",
            campaign_id="cam_01J00000000000000000000000",
            campaign_revision=0,
            idempotency_key="idempotent-demo",
            correlation_id="corr-timezone-demo",
            requested_at=datetime(2026, 7, 18, 12, 0),
        )


def test_turn_command_carries_idempotency_and_expected_revision() -> None:
    command = SubmitTurnCommand(
        session_id="ses_01J00000000000000000000000",
        turn_id="trn_01J00000000000000000000005",
        owner_id="user_demo",
        action="I ask Mara what she saw.",
        expected_revision=4,
        idempotency_key="turn-demo-idempotency",
        correlation_id="corr-turn-demo",
    )

    serialized = command.model_dump(mode="json", by_alias=True)
    assert serialized["expectedRevision"] == 4
    assert serialized["idempotencyKey"] == "turn-demo-idempotency"


def test_current_imports_reexport_neutral_game_contracts() -> None:
    assert api_models.AdventurePlan is AdventurePlan
    opening = OpeningView(
        title="A title",
        scene="A scene",
        character_name="Elia",
        pronouns="she/her",
        archetype="Bell keeper",
        appearance="A traveler in a weathered gray cloak.",
        background="She returned to the village after many years away.",
        desire="Find her brother",
        connection="The bell caused her exile",
        strength="Reads runes",
        flaw="Refuses help",
        meaningful_item="A tuning fork",
        known_facts=("The tower is old", "Mara knows the mill"),
        opening_choices=("Inspect", "Ask Mara", "Climb the tower"),
    )
    assert OpeningView.model_validate_json(opening.model_dump_json()) == opening


def test_domain_packages_do_not_import_frameworks_or_adapters() -> None:
    violations: list[str] = []
    for root in DOMAIN_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: list[str] = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported = [node.module]
                for module in imported:
                    if module.split(".", maxsplit=1)[0] in FORBIDDEN_TOP_LEVEL or module.startswith(
                        FORBIDDEN_INTERNAL
                    ):
                        violations.append(f"{path.relative_to(root)} imports {module}")

    assert violations == []

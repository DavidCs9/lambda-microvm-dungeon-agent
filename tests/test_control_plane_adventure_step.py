from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dungeon_agent.control_plane.domain.models import CreateSessionWorkflowInput, SessionId
from dungeon_agent.control_plane.steps.adventure import AdventureStep
from dungeon_agent.domain.game import AdventurePlan, LanguageCode
from tests.test_adventure import sample_plan


class FakeArchitect:
    def __init__(self, adventure: AdventurePlan) -> None:
        self.adventure = adventure
        self.languages: list[LanguageCode] = []

    def create(self, language: LanguageCode) -> AdventurePlan:
        self.languages.append(language)
        return self.adventure


class MemoryAdventurePlanStore:
    def __init__(self) -> None:
        self.saved: dict[str, AdventurePlan] = {}

    def save(self, session_id: SessionId, adventure: AdventurePlan) -> str:
        self.saved[session_id] = adventure
        return f"dynamodb://sessions/{session_id}/adventure"


def workflow_input(language: LanguageCode) -> CreateSessionWorkflowInput:
    return CreateSessionWorkflowInput(
        session_id="ses_01J00000000000000000000000",
        owner_id="user_demo",
        language=language,
        idempotency_key="adventure-step-demo",
        correlation_id="corr-adventure-step",
        requested_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )


def clock(values: tuple[float, ...]) -> Iterator[float]:
    return iter(values)


@pytest.mark.parametrize("language", ["en", "es"])
def test_step_persists_validated_bilingual_plan_and_returns_small_reference(
    language: LanguageCode,
) -> None:
    architect = FakeArchitect(sample_plan())
    plans = MemoryAdventurePlanStore()
    times = clock((10.0, 10.125))
    step = AdventureStep(architect, plans, monotonic=lambda: next(times))

    result = step.handle(workflow_input(language).model_dump(mode="json", by_alias=True))

    assert result == {
        "schemaVersion": 1,
        "sessionId": "ses_01J00000000000000000000000",
        "language": language,
        "correlationId": "corr-adventure-step",
        "adventureRef": "dynamodb://sessions/ses_01J00000000000000000000000/adventure",
        "latencyMs": 125,
    }
    assert architect.languages == [language]
    assert plans.saved["ses_01J00000000000000000000000"].title == "The Storm Bell"
    assert "secrets" not in result
    assert "adventure" not in result


def test_step_revalidates_untrusted_architect_output_before_persisting() -> None:
    invalid = sample_plan().model_copy(update={"starting_location_id": "missing"})
    plans = MemoryAdventurePlanStore()
    step = AdventureStep(FakeArchitect(invalid), plans)

    with pytest.raises(ValidationError, match="starting location must exist"):
        step.execute(workflow_input("en"))

    assert plans.saved == {}


def test_handler_rejects_invalid_workflow_input_before_generation() -> None:
    architect = FakeArchitect(sample_plan())
    step = AdventureStep(architect, MemoryAdventurePlanStore())
    raw = workflow_input("en").model_dump(mode="json", by_alias=True)
    raw["language"] = "fr"

    with pytest.raises(ValidationError):
        step.handle(raw)

    assert architect.languages == []

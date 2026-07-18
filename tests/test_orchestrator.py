from typing import cast
from unittest.mock import Mock

import pytest

from dungeon_agent.orchestrator.agents import AdventureArchitect, DungeonMaster
from dungeon_agent.orchestrator.game import DungeonOrchestrator
from dungeon_agent.orchestrator.locales import SPANISH, select_language
from dungeon_agent.orchestrator.observability import SessionMetrics
from dungeon_agent.orchestrator.session import MicrovmSession
from tests.test_adventure import proposal, sample_plan


def orchestrator_with_mocks(
    *, language: str = "en"
) -> tuple[DungeonOrchestrator, Mock, Mock, Mock, SessionMetrics]:
    session = Mock(spec=MicrovmSession)
    architect = Mock(spec=AdventureArchitect)
    dungeon_master = Mock(spec=DungeonMaster)
    metrics = SessionMetrics.start("us.amazon.nova-micro-v1:0")
    locale = SPANISH if language == "es" else None
    orchestrator = DungeonOrchestrator(
        session,
        architect,
        dungeon_master,
        metrics,
        *(tuple([locale]) if locale is not None else ()),
    )
    return orchestrator, session, architect, dungeon_master, metrics


def world_data(*, status: str = "active") -> dict[str, object]:
    return {
        "revision": 1,
        "language": "en",
        "plan": sample_plan().model_dump(mode="json"),
        "location_id": "square",
        "inventory": [],
        "health": 3,
        "facts": ["The storm is close"],
        "status": status,
        "last_result": {
            "action": "build a bridge",
            "intent": "cross the flood",
            "success": True,
            "narration": "The improvised bridge holds.",
            "roll": 16,
            "difficulty": 12,
            "suggestions": ["Cross it", "Call Mara"],
        },
    }


def test_opening_generates_and_starts_a_new_adventure() -> None:
    orchestrator, session, architect, _, _ = orchestrator_with_mocks()
    architect.create.return_value = sample_plan()
    session.start_adventure.return_value = world_data()

    assert orchestrator.opening_scene() == sample_plan().opening
    architect.create.assert_called_once_with("en")
    session.start_adventure.assert_called_once()


def test_free_form_action_is_adjudicated_then_validated_by_microvm() -> None:
    orchestrator, session, _, dungeon_master, _ = orchestrator_with_mocks()
    session.read_world.return_value = world_data()
    dungeon_master.adjudicate.return_value = proposal()
    session.apply_turn.return_value = world_data()

    turn = orchestrator.take_turn("  Build a bridge from broken tables  ")

    assert turn.narration == "The improvised bridge holds."
    assert turn.roll == 16
    dungeon_master.adjudicate.assert_called_once()
    session.apply_turn.assert_called_once_with(
        "Build a bridge from broken tables", dungeon_master.adjudicate.return_value
    )


def test_rejected_model_change_is_repaired_once() -> None:
    orchestrator, session, _, dungeon_master, _ = orchestrator_with_mocks()
    session.read_world.return_value = world_data()
    first, repaired = proposal(), proposal(requires_roll=False, difficulty=None)
    dungeon_master.adjudicate.side_effect = [first, repaired]
    session.apply_turn.side_effect = [
        RuntimeError("apply turn returned HTTP 409: unknown item"),
        world_data(),
    ]

    turn = orchestrator.take_turn("improvise something unexpected")

    assert turn.success
    assert dungeon_master.adjudicate.call_count == 2
    assert session.apply_turn.call_count == 2


def test_generated_state_summary_is_human_readable() -> None:
    orchestrator, session, _, _, _ = orchestrator_with_mocks()
    session.read_world.return_value = world_data()

    assert orchestrator.state_summary() == (
        "Location: Square\n"
        "Inventory: Empty\n"
        "Objective: Recover the storm bell and ring it from the old tower.\n"
        "Health: 3/3\n"
        "Time remaining: 9\n"
        "Status: active\n"
        "Turns played: 1"
    )


def test_spanish_is_an_official_language_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "1")
    assert select_language(None) is SPANISH
    assert select_language("es") is SPANISH


def test_stats_summary_includes_tokens_and_cost() -> None:
    orchestrator, _, _, _, metrics = orchestrator_with_mocks(language="es")
    metrics.record(input_tokens=1_000, output_tokens=100, latency_ms=750)

    assert "Tokens totales: 1,100" in orchestrator.stats_summary()
    assert "Costo estimado del modelo: $0.00004900 USD" in orchestrator.stats_summary()


@pytest.mark.parametrize("action", ["", "   ", "x" * 501])
def test_orchestrator_rejects_invalid_actions(action: str) -> None:
    orchestrator, session, _, dungeon_master, _ = orchestrator_with_mocks()

    with pytest.raises(ValueError):
        orchestrator.take_turn(action)

    cast(Mock, session.apply_turn).assert_not_called()
    cast(Mock, dungeon_master.adjudicate).assert_not_called()

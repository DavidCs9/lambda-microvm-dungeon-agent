from typing import cast
from unittest.mock import Mock

import pytest

from scripts.dungeon.game import DungeonOrchestrator
from scripts.dungeon.locales import SPANISH, select_language
from scripts.dungeon.narrator import BedrockNarrator
from scripts.dungeon.session import MicrovmSession


def test_orchestrator_persists_action_before_narration() -> None:
    session = Mock(spec=MicrovmSession)
    narrator = Mock(spec=BedrockNarrator)
    world = {"revision": 1, "story": ["Inspect the machine"]}
    session.apply_action.return_value = world
    narrator.narrate.return_value = "A brass key glints beneath the console."
    orchestrator = DungeonOrchestrator(session, narrator)

    result = orchestrator.take_turn("  Inspect the machine  ")

    assert result == "A brass key glints beneath the console."
    session.apply_action.assert_called_once_with("Inspect the machine")
    narrator.narrate.assert_called_once_with("Inspect the machine", world)


def test_state_summary_is_human_readable() -> None:
    session = Mock(spec=MicrovmSession)
    narrator = Mock(spec=BedrockNarrator)
    session.read_world.return_value = {
        "revision": 2,
        "location": "The Snapshot Tavern",
        "inventory": ["brass key"],
    }
    orchestrator = DungeonOrchestrator(session, narrator)

    assert orchestrator.state_summary() == (
        "Location: The Snapshot Tavern\nInventory: brass key\nTurns played: 2"
    )


def test_spanish_is_an_official_language_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "1")

    assert select_language(None) is SPANISH
    assert select_language("es") is SPANISH


def test_spanish_state_summary_is_localized() -> None:
    session = Mock(spec=MicrovmSession)
    narrator = Mock(spec=BedrockNarrator)
    session.read_world.return_value = {
        "revision": 1,
        "location": "The Snapshot Tavern",
        "inventory": [],
    }
    orchestrator = DungeonOrchestrator(session, narrator, SPANISH)

    assert orchestrator.state_summary() == (
        "Ubicación: La Taberna Snapshot\nInventario: Vacío\nTurnos jugados: 1"
    )


@pytest.mark.parametrize("action", ["", "   ", "x" * 501])
def test_orchestrator_rejects_invalid_actions(action: str) -> None:
    session = Mock(spec=MicrovmSession)
    narrator = Mock(spec=BedrockNarrator)
    orchestrator = DungeonOrchestrator(session, narrator)

    with pytest.raises(ValueError):
        orchestrator.take_turn(action)

    cast(Mock, session.apply_action).assert_not_called()
    cast(Mock, narrator.narrate).assert_not_called()

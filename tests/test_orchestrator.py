from typing import cast
from unittest.mock import Mock

import pytest

from scripts.orchestrator import BedrockNarrator, DungeonOrchestrator, MicrovmSession


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


@pytest.mark.parametrize("action", ["", "   ", "x" * 501])
def test_orchestrator_rejects_invalid_actions(action: str) -> None:
    session = Mock(spec=MicrovmSession)
    narrator = Mock(spec=BedrockNarrator)
    orchestrator = DungeonOrchestrator(session, narrator)

    with pytest.raises(ValueError):
        orchestrator.take_turn(action)

    cast(Mock, session.apply_action).assert_not_called()
    cast(Mock, narrator.narrate).assert_not_called()

from unittest.mock import Mock

from dungeon_agent.orchestrator.locales import SPANISH
from dungeon_agent.orchestrator.narrator import BedrockNarrator


def test_failed_outcome_uses_rules_text_without_calling_model() -> None:
    client = Mock()
    narrator = BedrockNarrator(client, "test-model", SPANISH)
    world: dict[str, object] = {
        "status": "active",
        "last_result": {
            "success": False,
            "summary": "La puerta está cerrada.",
            "consequence": "Necesitas encontrar la llave.",
        },
    }

    assert narrator.narrate("ya salí", world) == (
        "La puerta está cerrada. Necesitas encontrar la llave."
    )
    client.converse.assert_not_called()


def test_terminal_outcome_uses_rules_text_without_calling_model() -> None:
    client = Mock()
    narrator = BedrockNarrator(client, "test-model", SPANISH)
    world: dict[str, object] = {
        "status": "won",
        "last_result": {
            "success": True,
            "summary": "La llave gira.",
            "consequence": "¡Escapaste de la taberna!",
        },
    }

    assert narrator.narrate("abrir puerta", world) == "La llave gira. ¡Escapaste de la taberna!"
    client.converse.assert_not_called()

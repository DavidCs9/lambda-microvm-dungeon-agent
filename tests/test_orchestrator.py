from typing import cast
from unittest.mock import Mock

import pytest

from dungeon_agent.orchestrator.game import DungeonOrchestrator
from dungeon_agent.orchestrator.locales import SPANISH, select_language
from dungeon_agent.orchestrator.narrator import BedrockNarrator
from dungeon_agent.orchestrator.observability import SessionMetrics
from dungeon_agent.orchestrator.session import MicrovmSession


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
        "objective": "Escape before collapse",
        "health": 3,
        "danger": 6,
        "status": "active",
    }
    orchestrator = DungeonOrchestrator(session, narrator)

    assert orchestrator.state_summary() == (
        "Location: The Snapshot Tavern\n"
        "Inventory: brass key\n"
        "Objective: Escape before collapse\n"
        "Health: 3/3\n"
        "Time remaining: 6/8\n"
        "Status: active\n"
        "Turns played: 2"
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
        "objective": "Escapa antes del colapso",
        "health": 3,
        "danger": 7,
        "status": "active",
    }
    orchestrator = DungeonOrchestrator(session, narrator, SPANISH)

    assert orchestrator.state_summary() == (
        "Ubicación: La Taberna Snapshot\n"
        "Inventario: Vacío\n"
        "Objetivo: Escapa antes del colapso\n"
        "Salud: 3/3\n"
        "Tiempo restante: 7/8\n"
        "Estado: active\n"
        "Turnos jugados: 1"
    )


def test_spanish_stats_summary_includes_tokens_and_cost() -> None:
    session = Mock(spec=MicrovmSession)
    narrator = Mock(spec=BedrockNarrator)
    narrator.metrics = SessionMetrics.start("us.amazon.nova-micro-v1:0")
    narrator.metrics.record(input_tokens=1_000, output_tokens=100, latency_ms=750)
    orchestrator = DungeonOrchestrator(session, narrator, SPANISH)

    assert orchestrator.stats_summary() == (
        "Estadísticas de la sesión LLM\n"
        "Modelo: us.amazon.nova-micro-v1:0\n"
        "Llamadas al modelo: 1\n"
        "Tokens de entrada: 1,000\n"
        "Tokens de salida: 100\n"
        "Tokens totales: 1,100\n"
        "Latencia total del modelo: 0.75 s\n"
        "Costo estimado del modelo: $0.00004900 USD"
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

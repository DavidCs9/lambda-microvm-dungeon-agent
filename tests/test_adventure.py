import pytest

from dungeon_agent.api.adventure import initial_world, resolve_action
from dungeon_agent.api.models import LanguageCode, WorldState


def play(language: LanguageCode, actions: list[str]) -> WorldState:
    world = initial_world(language)
    for action in actions:
        world = resolve_action(world, action)
    return world


@pytest.mark.parametrize(
    ("language", "actions"),
    [
        (
            "en",
            ["look around", "enter kitchen", "search drawer", "take key", "return", "open door"],
        ),
        (
            "es",
            [
                "mirar alrededor",
                "entrar a la cocina",
                "buscar cajón",
                "tomar llave",
                "volver a la sala principal",
                "abrir puerta",
            ],
        ),
    ],
)
def test_player_can_escape_in_each_language(language: LanguageCode, actions: list[str]) -> None:
    world = play(language, actions)

    assert world.status == "won"
    assert "escaped" in world.completed_events
    assert world.last_result is not None
    assert world.last_result.success is True


def test_danger_clock_can_end_the_adventure() -> None:
    world = play("en", [f"wait {turn}" for turn in range(8)])

    assert world.status == "lost"
    assert world.health == 0
    assert world.danger == 0
    assert world.ending is not None

    unchanged = resolve_action(world, "open door")
    assert unchanged.revision == world.revision
    assert unchanged.last_result is not None
    assert unchanged.last_result.success is False


def test_locked_door_and_empty_tavern_give_simple_guidance() -> None:
    locked = resolve_action(initial_world(), "open door")
    conversation = resolve_action(initial_world(), "talk to someone")

    assert locked.last_result is not None
    assert locked.last_result.success is False
    assert conversation.last_result is not None
    assert conversation.last_result.success is False
    assert len(conversation.last_result.suggestions) >= 1


def test_inspection_and_return_preserve_discovered_state() -> None:
    world = play(
        "en",
        ["look around", "enter kitchen", "search drawer", "take key", "return"],
    )

    assert world.location == "The Locked Tavern"
    assert "brass key" in world.inventory
    assert len(world.discovered_clues) == 2

"""Deterministic rules for the Escape the Locked Tavern one-shot."""

import re
from dataclasses import dataclass
from typing import cast

from dungeon_agent.api.models import (
    ActionIntent,
    ActionResult,
    GameStatus,
    LanguageCode,
    WorldState,
)
from dungeon_agent.localization import language_section, language_text, language_translation

TAVERN = "The Locked Tavern"
KITCHEN = "The Tavern Kitchen"


@dataclass
class MutableWorld:
    location: str
    inventory: list[str]
    clues: list[str]
    relationships: dict[str, int]
    events: list[str]

    @classmethod
    def from_state(cls, state: WorldState) -> MutableWorld:
        return cls(
            location=state.location,
            inventory=list(state.inventory),
            clues=list(state.discovered_clues),
            relationships=dict(state.npc_relationships),
            events=list(state.completed_events),
        )


def initial_world(language: LanguageCode = "en") -> WorldState:
    return WorldState(
        revision=0,
        language=language,
        location=TAVERN,
        inventory=[],
        story=[language_text(language, "adventure", "initialStory")],
        health=3,
        danger=8,
        objective=language_text(language, "adventure", "objective"),
        discovered_clues=[],
        npc_relationships={},
        completed_events=[],
        status="active",
    )


def resolve_action(state: WorldState, action: str) -> WorldState:
    if state.status != "active":
        return state.model_copy(
            update={
                "last_result": ActionResult(
                    intent="unknown",
                    success=False,
                    summary=_localize(state.language, "This adventure has already ended."),
                    consequence=state.ending
                    or _localize(state.language, "Start a new session to play again."),
                    suggestions=[_localize(state.language, "Start a new MicroVM session")],
                )
            }
        )

    text = action.casefold()
    world = MutableWorld.from_state(state)
    intent = classify_intent(text, state.language)
    success, summary, consequence, suggestions = _resolve(world, intent, text, state.language)
    summary = _localize(state.language, summary)
    consequence = _localize(state.language, consequence)
    suggestions = [_localize(state.language, suggestion) for suggestion in suggestions]
    danger = max(0, state.danger - 1)
    health = state.health
    status: GameStatus = state.status
    ending = state.ending

    if danger == 0:
        health = 0
        status = "lost"
        ending = _localize(
            state.language, "Time runs out and you remain locked inside the tavern."
        )
        consequence = ending
        suggestions = [_localize(state.language, "Start a new session and try another path")]

    if "escaped" in world.events:
        status = "won"
        ending = _localize(
            state.language,
            "You unlock the front door and step outside. You escaped the tavern!",
        )
        consequence = ending
        suggestions = [_localize(state.language, "Celebrate your escape")]

    result = ActionResult(
        intent=intent,
        success=success,
        summary=summary,
        consequence=consequence,
        suggestions=suggestions,
    )
    return state.model_copy(
        update={
            "revision": state.revision + 1,
            "location": world.location,
            "inventory": world.inventory,
            "story": [*state.story, action, consequence],
            "health": health,
            "danger": danger,
            "discovered_clues": world.clues,
            "npc_relationships": world.relationships,
            "completed_events": world.events,
            "status": status,
            "ending": ending,
            "last_result": result,
        }
    )


def classify_intent(text: str, language: LanguageCode) -> ActionIntent:
    vocabulary = language_section(language, "adventure").get("intentKeywords")
    if not isinstance(vocabulary, dict):
        raise ValueError(f"Language resource {language}.adventure.intentKeywords must be an object")
    for raw_intent, raw_words in vocabulary.items():
        if not isinstance(raw_intent, str) or not isinstance(raw_words, list):
            raise ValueError(f"Invalid intent vocabulary in language resource {language}")
        words = [word for word in raw_words if isinstance(word, str)]
        if any(re.search(rf"\b{re.escape(word.casefold())}\b", text) for word in words):
            return cast(ActionIntent, raw_intent)
    return "unknown"


def _resolve(
    world: MutableWorld,
    intent: ActionIntent,
    text: str,
    language: LanguageCode,
) -> tuple[bool, str, str, list[str]]:
    if intent == "talk":
        return (
            False,
            "No one else is in the tavern.",
            "You will need to find the key yourself.",
            _suggestions_for(world.location),
        )

    if intent == "inspect" and world.location == TAVERN:
        _add_once(world.clues, "The front door is locked. The kitchen is open.")
        return (
            True,
            "The front door is locked and needs a key.",
            "An open doorway leads to the kitchen.",
            ["Enter the kitchen", "Try the front door"],
        )

    if intent == "explore":
        if world.location == TAVERN and _matches_navigation(text, language, "kitchen"):
            world.location = KITCHEN
            return (
                True,
                "You enter the small kitchen.",
                "There is a wooden table, a cupboard, and one closed drawer.",
                ["Search the drawer", "Look around", "Return to the main room"],
            )
        if world.location == KITCHEN and _matches_navigation(text, language, "tavern"):
            world.location = TAVERN
            return (
                True,
                "You return to the main room.",
                "The locked front door is directly ahead.",
                ["Unlock the front door", "Return to the kitchen"],
            )

    if intent == "take" and world.location == KITCHEN:
        _add_once(world.inventory, "brass key")
        _add_once(world.events, "found_key")
        return (
            True,
            "You take the brass key from the drawer.",
            "It looks like it fits the front door.",
            ["Return to the main room", "Unlock the front door"],
        )

    if intent == "inspect" and world.location == KITCHEN:
        _add_once(world.clues, "A brass key is inside the kitchen drawer.")
        return (
            True,
            "You open the drawer and find a brass key.",
            "The key is within reach.",
            ["Take the brass key", "Return to the main room"],
        )

    if intent in {"escape", "use"} and world.location == TAVERN:
        if "brass key" in world.inventory:
            _add_once(world.events, "escaped")
            return (
                True,
                "The brass key turns in the lock.",
                "The front door opens.",
                ["Step outside"],
            )
        return (
            False,
            "The front door is locked.",
            "You need to find its key.",
            ["Look around", "Enter the kitchen"],
        )

    return (
        False,
        "Your idea does not change the situation yet.",
        "Try one of the simple actions shown in the suggestions.",
        _suggestions_for(world.location),
    )


def _suggestions_for(location: str) -> list[str]:
    if location == KITCHEN:
        return ["Search the drawer", "Take the brass key", "Return to the main room"]
    return ["Look around", "Enter the kitchen", "Try the front door"]


def _matches_navigation(text: str, language: LanguageCode, target: str) -> bool:
    navigation = language_section(language, "adventure").get("navigationKeywords")
    if not isinstance(navigation, dict):
        raise ValueError(
            f"Language resource {language}.adventure.navigationKeywords must be an object"
        )
    words = navigation.get(target)
    if not isinstance(words, list):
        raise ValueError(f"Language resource {language} has no navigation target {target}")
    return any(isinstance(word, str) and word.casefold() in text for word in words)


def _add_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _localize(language: LanguageCode, value: str) -> str:
    return language_translation(language, "adventure", value)

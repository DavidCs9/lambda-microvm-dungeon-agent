"""Deterministic rules for the Escape the Snapshot Tavern one-shot."""

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

TAVERN = "The Snapshot Tavern"
CELLAR = "The Snapshot Cellar"


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
        npc_relationships={"Mira": 0},
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
            state.language, "The unstable snapshot collapses with you still trapped inside."
        )
        consequence = ending
        suggestions = [_localize(state.language, "Start a new session and try another path")]

    if "tavern_stabilized" in world.events:
        status = "won"
        ending = _localize(
            state.language,
            "You stabilize the MicroVM and save Mira's tavern from the collapsing snapshot.",
        )
        consequence = ending
        suggestions = [_localize(state.language, "Celebrate with Mira")]
    elif "escaped" in world.events:
        status = "won"
        ending = _localize(
            state.language,
            "You unlock the snapshot door and escape as the tavern dissolves behind you.",
        )
        consequence = ending
        suggestions = [_localize(state.language, "Look back at the fading tavern")]

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
    if intent == "talk" and world.location == TAVERN:
        world.relationships["Mira"] = 1
        _add_once(world.clues, "Mira says a tuning fork can stabilize the cellar machine.")
        _add_once(world.inventory, "silver tuning fork")
        _add_once(world.events, "befriended_mira")
        return (
            True,
            "Mira trusts you with her silver tuning fork.",
            "She points to a trapdoor beneath the hearth and warns that time is running out.",
            ["Enter the cellar", "Inspect the snapshot door", "Ask Mira about the machine"],
        )

    if intent == "inspect" and world.location == TAVERN:
        _add_once(world.clues, "The cellar trapdoor is hidden beneath the hearth rug.")
        return (
            True,
            "You discover a trapdoor beneath the hearth rug.",
            "Cold blue light pulses through its frame in time with the tavern's shaking.",
            ["Enter the cellar", "Talk to Mira", "Inspect the snapshot door"],
        )

    if intent == "explore":
        if world.location == TAVERN and _matches_navigation(text, language, "cellar"):
            world.location = CELLAR
            return (
                True,
                "You descend into the Snapshot Cellar.",
                "A brass key hangs beside a violently humming machine.",
                ["Take the brass key", "Inspect the machine", "Return to the tavern"],
            )
        if world.location == CELLAR and _matches_navigation(text, language, "tavern"):
            world.location = TAVERN
            return (
                True,
                "You climb back into the tavern.",
                "The snapshot door flickers while Mira braces the bar.",
                ["Open the snapshot door", "Talk to Mira", "Return to the cellar"],
            )

    if intent == "take" and world.location == CELLAR:
        _add_once(world.inventory, "brass snapshot key")
        _add_once(world.events, "found_key")
        return (
            True,
            "You take the brass snapshot key.",
            "It is warm and fits the lock on the tavern's glowing door.",
            ["Return to the tavern", "Inspect the machine", "Use the tuning fork"],
        )

    if intent == "inspect" and world.location == CELLAR:
        _add_once(world.clues, "The machine has a fork-shaped stabilizer socket.")
        return (
            True,
            "You find a fork-shaped socket in the unstable machine.",
            "The machine can be stabilized if you have the matching instrument.",
            ["Use the tuning fork", "Take the brass key", "Return to the tavern"],
        )

    if intent == "use" and world.location == CELLAR:
        if "silver tuning fork" in world.inventory:
            _add_once(world.events, "tavern_stabilized")
            return (
                True,
                "The silver tuning fork resonates with the machine.",
                "The violent shaking stops and the Snapshot Tavern becomes stable.",
                ["Celebrate with Mira"],
            )
        return (
            False,
            "The machine rejects your attempt.",
            "Its socket needs a specific fork-shaped instrument.",
            ["Inspect the machine", "Return and talk to Mira"],
        )

    if intent == "escape" and world.location == TAVERN:
        if "brass snapshot key" in world.inventory:
            _add_once(world.events, "escaped")
            return (
                True,
                "The brass key turns in the snapshot door.",
                "The doorway opens onto solid ground beyond the failing MicroVM.",
                ["Step through the door"],
            )
        return (
            False,
            "The snapshot door is locked.",
            "A brass keyhole glows beneath its handle.",
            ["Search the tavern", "Talk to Mira", "Enter the cellar"],
        )

    return (
        False,
        "Your idea does not change the situation yet.",
        "The tavern shudders again; try describing what you inspect, use, or whom you approach.",
        _suggestions_for(world.location),
    )


def _suggestions_for(location: str) -> list[str]:
    if location == CELLAR:
        return ["Inspect the machine", "Take the brass key", "Return to the tavern"]
    return ["Look around", "Talk to Mira", "Try the snapshot door"]


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

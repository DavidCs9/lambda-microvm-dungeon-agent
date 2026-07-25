import json
import re
from typing import Any, cast

from dungeon_agent.domain.game import LanguageCode, StateChanges, TurnProposal

_ITEM_ACTION_WORDS = ("item", "key", "sword", "potion", "artifact", "tool", "weapon")
_ITEM_VERBS = ("use", "throw", "drop", "remove", "give", "equip", "insert", "carry")


def _unknown_item_proposal(
    action: str, world: dict[str, object], language: LanguageCode
) -> TurnProposal | None:
    """Reject obvious unknown-item actions before spending an FM call."""
    lowered = action.casefold()
    if not any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _ITEM_ACTION_WORDS):
        return None
    if not any(re.search(rf"\b{re.escape(verb)}\b", lowered) for verb in _ITEM_VERBS):
        return None
    plan = world.get("plan")
    if not isinstance(plan, dict):
        return None
    items = plan.get("items")
    inventory = world.get("inventory")
    if not isinstance(items, list) or not isinstance(inventory, list):
        return None
    known = {
        str(value).casefold()
        for item in items
        if isinstance(item, dict)
        for value in (item.get("id"), item.get("name"))
        if isinstance(value, str)
    }
    if any(item and item in lowered for item in known):
        return None
    if language == "es":
        intent = "Intento de usar un objeto desconocido."
        narration = "El objeto desconocido no puede cambiar el mundo."
        fact = "El objeto desconocido no puede cambiar el mundo."
        suggestions = ["Usa un objeto conocido.", "Prueba otra acción."]
    else:
        intent = "Attempt to use an unknown item."
        narration = "The unknown item cannot change the world."
        fact = "The unknown item cannot change the world."
        suggestions = ["Use a known item.", "Try another action."]
    return TurnProposal(
        intent=intent,
        requires_roll=False,
        difficulty=None,
        stat=None,
        success_narration=narration,
        failure_narration=narration,
        success_changes=StateChanges(),
        failure_changes=StateChanges(add_facts=[fact]),
        suggestions=suggestions,
    )


def _language_name(language: LanguageCode) -> str:
    return "Spanish" if language == "es" else "English"


class DungeonMaster:
    """Data-plane agent: proposes turn outcomes for the MicroVM to validate/apply."""

    def __init__(self, agent: Any, language: LanguageCode) -> None:
        self.agent = agent
        self.language = language

    def adjudicate(
        self,
        action: str,
        world: dict[str, object],
        rejection_feedback: str | None = None,
    ) -> TurnProposal:
        guarded = _unknown_item_proposal(action, world, self.language)
        if guarded is not None:
            return guarded
        language_name = _language_name(self.language)
        result = self.agent.invoke(
            system=(
                "Be a fair dungeon master. Roll only for risk, use declared IDs in changes, move "
                "failures forward, set earned victory only, and narrate in 1-3 vivid sentences. "
                "Respect the current inventory: only add_items/remove_items that exist in "
                "plan.items, never remove an item the player is not carrying, and reference "
                "carried items naturally in the narration. "
                "When a roll is required, set stat to the attribute that governs the action "
                "(might, agility, wits, charm, or resolve); the hero's stat value in "
                "player_character.stats is added to the d20, so weigh it when setting difficulty."
            ),
            prompt=json.dumps(
                {
                    "instruction": f"Resolve this turn entirely in {language_name}.",
                    "playerAction": action,
                    "world": world,
                    "previousProposalRejection": rejection_feedback,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            prompt_variables={
                "language_name": language_name,
                "action": action,
                "world_json": json.dumps(
                    world,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "rejection_feedback": (
                    rejection_feedback
                    if rejection_feedback is not None
                    else "No previous proposal rejection."
                ),
            },
            tool_name="resolve_turn",
            tool_description="Return the success and failure branches for this player action.",
            output_model=TurnProposal,
            max_tokens=1_200,
            temperature=0.65,
        )
        return cast(TurnProposal, result)

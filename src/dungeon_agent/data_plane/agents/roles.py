import json
from typing import Any, cast

from dungeon_agent.domain.game import LanguageCode, TurnProposal


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

"""Framework-neutral agent roles backed by a structured model adapter."""

import json
from typing import Protocol, TypeVar

from pydantic import BaseModel

from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter, TurnProposal

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class StructuredAgentPort(Protocol):
    def invoke(
        self,
        *,
        system: str,
        prompt: str,
        tool_name: str,
        tool_description: str,
        output_model: type[OutputModel],
        max_tokens: int,
        temperature: float,
    ) -> OutputModel: ...


def _language_name(language: LanguageCode) -> str:
    return "Spanish" if language == "es" else "English"


class AdventureArchitect:
    """Create one small, replayable adventure for a new session."""

    def __init__(self, agent: StructuredAgentPort) -> None:
        self.agent = agent

    def create(self, language: LanguageCode) -> AdventurePlan:
        language_name = _language_name(language)
        return self.agent.invoke(
            system=(
                "You design compact tabletop fantasy one-shots. Create coherent, playful "
                "adventures that support improvisation and at least three meaningfully different "
                "solutions. Keep the lore simple enough to understand immediately. IDs must be "
                "lowercase ASCII snake_case. Every exit must reference a declared location. Do not "
                "copy commercial settings, characters, or stories."
            ),
            prompt=(
                f"Create a brand-new 10 to 15 minute adventure entirely in {language_name}. "
                "Give it one clear objective, 3 to 5 connected locations, 1 or 2 characters with "
                "useful motivations, a few usable items, and secrets that permit clever solutions. "
                "The opening must state the immediate situation and objective without solving it. "
                "Populate every field in the tool, including secrets and max_turns. Keep every "
                "description and motivation under 250 characters."
            ),
            tool_name="create_adventure",
            tool_description="Return the complete validated adventure plan.",
            output_model=AdventurePlan,
            max_tokens=3_000,
            temperature=0.9,
        )


class CharacterArchitect:
    """Create a protagonist with strong reasons to inhabit the generated world."""

    def __init__(self, agent: StructuredAgentPort) -> None:
        self.agent = agent

    def create(self, language: LanguageCode, adventure: AdventurePlan) -> PlayerCharacter:
        language_name = _language_name(language)
        return self.agent.invoke(
            system=(
                "You design memorable player characters for short tabletop role-playing games. "
                "Create a person the player can inhabit, not a generic class or a long biography. "
                "Every detail must create a playable decision, emotional stake, relationship, or "
                "useful approach. Connect the protagonist tightly to the supplied adventure "
                "without revealing its secrets. Give the player room to choose their personality "
                "and actions. The three opening choices must represent investigation, social "
                "interaction, and a risky direct approach; they are examples, never restrictions. "
                "Do not copy characters or settings from commercial fiction."
            ),
            prompt=json.dumps(
                {
                    "instruction": (
                        f"Create one protagonist entirely in {language_name}. The player must "
                        "immediately understand who they are, what they want, why this objective "
                        "matters personally, what they already know, and three different ways to "
                        "begin. Keep the complete character briefing concise and playable."
                    ),
                    "adventure": adventure.model_dump(mode="json"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            tool_name="create_player_character",
            tool_description="Return a complete protagonist grounded in the supplied adventure.",
            output_model=PlayerCharacter,
            max_tokens=2_000,
            temperature=0.85,
        )


class DungeonMaster:
    """Interpret a free-form player action into two validated outcome branches."""

    def __init__(self, agent: StructuredAgentPort, language: LanguageCode) -> None:
        self.agent = agent
        self.language = language

    def adjudicate(
        self,
        action: str,
        world: dict[str, object],
        rejection_feedback: str | None = None,
    ) -> TurnProposal:
        language_name = _language_name(self.language)
        return self.agent.invoke(
            system=(
                "You are a fair, energetic tabletop dungeon master. Reward creative ideas and "
                "allow plausible approaches that were not anticipated by the adventure author. "
                "Use a d20 roll only when an action is risky or uncertain; obvious actions succeed "
                "automatically. A difficulty of 8 is easy, 12 moderate, 15 hard, and 18 extreme. "
                "Never claim state changes only in narration: encode every location, item, fact, "
                "health, or victory change in the matching changes object. Only use declared IDs. "
                "Summarize intent in fewer than 200 characters. Set objective_complete only when "
                "the stated objective is genuinely accomplished. Failures should move the story "
                "forward with a consequence, not simply reject the idea. Keep each narration to "
                "1 to 3 vivid sentences and never act for the player."
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
            tool_name="resolve_turn",
            tool_description="Return the success and failure branches for this player action.",
            output_model=TurnProposal,
            max_tokens=1_200,
            temperature=0.65,
        )

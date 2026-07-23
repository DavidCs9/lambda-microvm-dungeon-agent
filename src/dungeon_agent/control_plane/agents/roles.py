import json
from typing import Any, cast

from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter, TurnProposal

ADVENTURE_THEME_SEED = "a floating market that drifts overnight"


def _language_name(language: LanguageCode) -> str:
    return "Spanish" if language == "es" else "English"


class AdventureArchitect:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def create(self, language: LanguageCode, *, theme_seed: str | None = None) -> AdventurePlan:
        language_name = _language_name(language)
        theme = theme_seed or ADVENTURE_THEME_SEED
        result = self.agent.invoke(
            system=(
                "Design a compact fantasy one-shot with declared exits, snake_case IDs, at least "
                "three solution paths, no commercial-fiction copies, and no silent bell/tower."
            ),
            prompt=(
                f"Create a 10-15 minute {language_name} adventure inspired by {theme}: objective, "
                "3-5 locations, 1-2 NPCs, useful items, secrets, max_turns, and short opening."
            ),
            tool_name="create_adventure",
            tool_description="Return the complete validated adventure plan.",
            output_model=AdventurePlan,
            max_tokens=3_000,
            temperature=0.9,
        )
        return cast(AdventurePlan, result)


class CharacterArchitect:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def create(
        self, language: LanguageCode, adventure: AdventurePlan, *, pronoun_seed: str | None = None
    ) -> PlayerCharacter:
        language_name = _language_name(language)
        pronouns = pronoun_seed if pronoun_seed is not None else _pronoun_seed(language)
        result = self.agent.invoke(
            system=(
                "Design one concise protagonist tied to the adventure, vary gender/presentation, "
                "hide secrets, and make choices investigative, social, and risky."
            ),
            prompt=json.dumps(
                {
                    "instruction": (
                        f"Create one concise protagonist in {language_name}: identity, desire, "
                        "personal stake, known facts, and three ways to begin. "
                        f"Put exactly these pronouns in the pronouns field: {pronouns}. "
                        "Align name, appearance, and grammar with that identity."
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
        return cast(PlayerCharacter, result)


def _pronoun_seed(language: LanguageCode) -> str:
    return "él / lo" if language == "es" else "he/him"


class DungeonMaster:
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
                "failures forward, set earned victory only, and narrate in 1-3 vivid sentences."
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
        return cast(TurnProposal, result)

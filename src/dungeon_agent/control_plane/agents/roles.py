import json
import secrets
from typing import Any, cast

from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter, TurnProposal

ADVENTURE_THEME_SEEDS: tuple[str, ...] = (
    "a floating market that drifts overnight",
    "a glass greenhouse trapped in perpetual dusk",
    "a courier guild whose maps keep lying",
    "a salt mine that sings when danger nears",
    "a lighthouse that points inland instead of to sea",
    "a traveling theater missing its lead mask",
    "a bridge toll that demands memories, not coin",
    "a river that bargains for names",
)

CHARACTER_PRONOUN_SEEDS: tuple[tuple[str, str], ...] = (
    ("él / lo", "he/him"),
    ("él / lo", "he/him"),
    ("ella / la", "she/her"),
    ("ella / la", "she/her"),
    ("elle / le", "they/them"),
)


def _language_name(language: LanguageCode) -> str:
    return "Spanish" if language == "es" else "English"


class AdventureArchitect:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def create(self, language: LanguageCode, *, theme_seed: str | None = None) -> AdventurePlan:
        language_name = _language_name(language)
        theme = theme_seed if theme_seed is not None else secrets.choice(ADVENTURE_THEME_SEEDS)
        result = self.agent.invoke(
            system=(
                "Design a compact fantasy one-shot with simple lore, declared exits, lowercase "
                "snake_case IDs, and at least three real solution paths. Do not copy commercial "
                "fiction or default to a silent bell/tower. Keep descriptions one short sentence."
            ),
            prompt=(
                f"Create a new 10-15 minute adventure in {language_name}, inspired by: {theme}. "
                "Include one objective, 3-5 connected locations, 1-2 motivated NPCs, useful "
                "items, secrets, max_turns, and a two-sentence opening under 180 characters."
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
                "Design one playable protagonist tightly tied to the adventure without revealing "
                "secrets. Keep prose short, vary gender/presentation, avoid commercial fiction, "
                "and make the three opening choices investigative, social, and risky."
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
    spanish, english = secrets.choice(CHARACTER_PRONOUN_SEEDS)
    return spanish if language == "es" else english


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
                "Be a fair, energetic dungeon master. Roll only for risky actions, encode every "
                "state change in changes using declared IDs, move failures forward, set victory "
                "only when earned, and keep narration to 1-3 vivid sentences."
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

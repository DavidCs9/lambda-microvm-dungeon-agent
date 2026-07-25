import json
from typing import Any, cast

from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter

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
                "3-5 locations, 1-2 NPCs, useful items, secrets, max_turns, and short opening. "
                "Also pick a small, coherent starting_inventory (0-2 item ids from items) that the "
                "protagonist plausibly already carries given the premise."
            ),
            prompt_variables={"language_name": language_name, "theme": theme},
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
                        "Align name, appearance, and grammar with that identity. "
                        "Set stats (might, agility, wits, charm, resolve) to a value of 1-3 each, "
                        "chosen freely and independently to fit the archetype. Do not balance "
                        "them: some heroes are broadly weak (mostly 1s), others exceptional "
                        "(mostly 3s). "
                        "Keep every string field short enough to satisfy the tool schema "
                        "maxLength constraints (prefer punchy one-liners)."
                    ),
                    "adventure": adventure.model_dump(mode="json"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            prompt_variables={
                "language_name": language_name,
                "pronouns": pronouns,
                "adventure_json": adventure.model_dump_json(),
            },
            tool_name="create_player_character",
            tool_description="Return a complete protagonist grounded in the supplied adventure.",
            output_model=PlayerCharacter,
            max_tokens=2_000,
            temperature=0.85,
        )
        # Clamp so persisted artifacts still load on MicroVM images with older caps.
        return _clamp_player_character(cast(PlayerCharacter, result))


_PLAYER_FIELD_CAPS = {
    "name": 50,
    "pronouns": 30,
    "archetype": 80,
    "appearance": 120,
    "background": 200,
    "desire": 120,
    "need": 120,
    "connection_to_adventure": 160,
    "strength": 100,
    "flaw": 100,
    "contradiction": 160,
    "npc_connection": 160,
    "meaningful_item": 100,
    "open_question": 160,
}


def _clamp_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    clipped = value[: max_length - 1].rstrip()
    return f"{clipped}…"


def _clamp_player_character(character: PlayerCharacter) -> PlayerCharacter:
    payload = character.model_dump(mode="python")
    for field, max_length in _PLAYER_FIELD_CAPS.items():
        payload[field] = _clamp_text(str(payload[field]), max_length)
    payload["known_facts"] = [_clamp_text(str(item), 160) for item in payload["known_facts"]]
    payload["opening_choices"] = [
        _clamp_text(str(item), 160) for item in payload["opening_choices"]
    ]
    return PlayerCharacter.model_validate(payload)


def _pronoun_seed(language: LanguageCode) -> str:
    return "él / lo" if language == "es" else "he/him"

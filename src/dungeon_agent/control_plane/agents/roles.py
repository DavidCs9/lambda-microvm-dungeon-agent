import json
import re
from hashlib import sha256
from typing import Any, cast

from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter

_CREATIVE_PROFILE_FAMILIES = (
    (
        "action",
        (
            "a mountain pass where a warband's siege engine awakens a stone giant",
            "a flooded fortress whose gates require a daring coordinated assault",
            "a monster-haunted canyon where the only bridge is collapsing under a caravan",
            "a village arena challenged by a champion who fights for an impossible claim",
        ),
    ),
    (
        "exploration",
        (
            "a glacier cave where shifting ice redraws the route to an underground garden",
            "a skyship stranded on the back of a giant walking toward the horizon",
            "a jungle ruin whose terraces sink into the earth after every loud sound",
            "a volcanic island where safe paths appear only during brief tides of ash",
        ),
    ),
    (
        "social",
        (
            "a bridge that appears only when two enemies agree on one thing",
            "a caravan carrying a living statue that wants to change destinations",
            "a dragon's court where three villages must negotiate a shared water right",
            "a river crossing that demands a cherished memory as its toll",
        ),
    ),
    (
        "mystery",
        (
            "a village that loses one street from its map every sunrise",
            "a mine where the excavated ore whispers names of people still alive",
            "a harvest festival where every contestant is secretly an impostor",
            "a lighthouse whose beam reveals a different future each night",
        ),
    ),
)
ADVENTURE_THEME_SEED = "a fresh fantasy situation with an unusual constraint"


def _campaign_digest(campaign_id: str) -> bytes:
    return sha256(campaign_id.encode("utf-8")).digest()


def campaign_theme_family(campaign_id: str) -> str:
    """Return a stable, balanced creative family for one campaign generation."""
    digest = _campaign_digest(campaign_id)
    return _CREATIVE_PROFILE_FAMILIES[
        int.from_bytes(digest[:2], "big") % len(_CREATIVE_PROFILE_FAMILIES)
    ][0]


def campaign_theme_seed(campaign_id: str) -> str:
    """Return a stable, varied creative brief for one campaign generation."""
    digest = _campaign_digest(campaign_id)
    family_index = int.from_bytes(digest[:2], "big") % len(_CREATIVE_PROFILE_FAMILIES)
    family, profiles = _CREATIVE_PROFILE_FAMILIES[family_index]
    profile = profiles[int.from_bytes(digest[2:4], "big") % len(profiles)]
    variation = digest.hex()[:8]
    return (
        f"Creative direction family: {family}. {profile}. Creative variation key {variation}; "
        "use it only as a tie-breaker and do not "
        "mention it in the adventure."
    )


def _language_name(language: LanguageCode) -> str:
    return "Spanish" if language == "es" else "English"


class AdventureArchitect:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def create(
        self,
        language: LanguageCode,
        *,
        theme_seed: str | None = None,
        campaign_id: str | None = None,
        metrics: Any | None = None,
    ) -> AdventurePlan:
        language_name = _language_name(language)
        theme = (
            f"{theme_seed or ADVENTURE_THEME_SEED}\n"
            f"OUTPUT LANGUAGE CONTRACT: write every human-readable field in {language_name} only. "
            "Do not mix languages, translate names and prose consistently, and do not use English "
            "fallback text when the requested language is Spanish."
        )
        result = self._invoke(language_name, theme, campaign_id=campaign_id, metrics=metrics)
        adventure = result
        if _has_language_leak(adventure, language):
            result = self._invoke(
                language_name,
                f"{theme}\nIMPORTANT REPAIR: the previous draft mixed languages. Rewrite every "
                f"human-readable field in {language_name} only.",
                campaign_id=campaign_id,
                metrics=metrics,
            )
            adventure = result
        return adventure

    def _invoke(
        self,
        language_name: str,
        theme: str,
        *,
        campaign_id: str | None,
        metrics: Any | None,
    ) -> AdventurePlan:
        result = self.agent.invoke(
            system=(
                "Design a compact fantasy one-shot with declared exits, snake_case IDs, at least "
                "three solution paths, no commercial-fiction copies, and no silent bell/tower. "
                "Build the objective as discovery, complication, and a separate final action. "
                "Every important item must have a concrete use tied to the objective, and every "
                "secret must be discoverable through play rather than dumped immediately. "
                "Proofread every generated string for natural grammar, agreement, punctuation, "
                "and clear wording. "
                "Honor the supplied creative brief as the story's central premise. Make the "
                "campaign materially distinct from common fantasy templates: do not default to "
                "a floating market, broken or silent bell, magical orchard, mirror academy, "
                "generic missing artifact, or dawn deadline unless the brief explicitly requires "
                "it. Do not reuse the same title pattern across campaigns."
            ),
            prompt=(
                f"Create a 10-15 minute {language_name} adventure inspired by {theme}: objective, "
                f"Every human-readable output field must be written entirely in {language_name}; "
                "this includes title, premise, objective, opening, locations, characters, items, "
                "and secrets. "
                "3-5 locations, 1-2 NPCs, useful items, secrets, max_turns, and short opening. "
                "Also pick a small, coherent starting_inventory (0-2 item ids from items) that the "
                "protagonist plausibly already carries given the premise. Make the final objective "
                "action explicit and distinct from merely discovering the solution."
            ),
            prompt_variables={"language_name": language_name, "theme": theme},
            tool_name="create_adventure",
            tool_description="Return the complete validated adventure plan.",
            output_model=AdventurePlan,
            max_tokens=3_000,
            temperature=0.9,
            request_metadata={"campaign_id": campaign_id} if campaign_id else None,
            metrics=metrics,
        )
        return cast(AdventurePlan, result)


_LANGUAGE_MARKERS = {
    "es": (
        {"el", "la", "los", "las", "una", "un", "que", "con", "para", "debe"},
        {"the", "you", "your", "must", "before", "with"},
    ),
    "en": (
        {"the", "you", "your", "must", "before", "with", "and"},
        {"el", "la", "los", "las", "una", "un", "que", "con", "para", "debe"},
    ),
}


def _has_language_leak(adventure: AdventurePlan, language: LanguageCode) -> bool:
    expected, foreign = _LANGUAGE_MARKERS[language]

    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [text for part in value.values() for text in strings(part)]
        if isinstance(value, list):
            return [text for part in value for text in strings(part)]
        return []

    for text in strings(adventure.model_dump(mode="json")):
        words = set(re.findall(r"[a-záéíóúüñ]{2,}", text.lower()))
        if words & foreign and not words & expected:
            return True
    return False


class CharacterArchitect:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def create(
        self,
        language: LanguageCode,
        adventure: AdventurePlan,
        *,
        pronoun_seed: str | None = None,
        campaign_id: str | None = None,
        metrics: Any | None = None,
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
            request_metadata={"campaign_id": campaign_id} if campaign_id else None,
            metrics=metrics,
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

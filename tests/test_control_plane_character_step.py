from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from dungeon_agent.control_plane.domain.enums import OpeningBlockKind
from dungeon_agent.control_plane.domain.models import CampaignId, OpeningDocument
from dungeon_agent.control_plane.steps.character import CharacterStep
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter
from tests.test_adventure import sample_plan, sample_player

CAMPAIGN_ID: CampaignId = "cam_01J00000000000000000000000"
ADVENTURE_REF = f"dynamodb://CAMPAIGN#{CAMPAIGN_ID}/ARTIFACT#ADVENTURE"
CHARACTER_REF = f"dynamodb://CAMPAIGN#{CAMPAIGN_ID}/ARTIFACT#CHARACTER"


class FakeCharacterArchitect:
    def __init__(self, character: PlayerCharacter) -> None:
        self.character = character
        self.calls: list[tuple[LanguageCode, AdventurePlan]] = []

    def create(self, language: LanguageCode, adventure: AdventurePlan) -> PlayerCharacter:
        self.calls.append((language, adventure))
        return self.character


class MemoryAdventurePlanLoader:
    def __init__(self, adventure: AdventurePlan) -> None:
        self.adventure = adventure
        self.loaded_refs: list[str] = []

    def load(self, adventure_ref: str) -> AdventurePlan:
        self.loaded_refs.append(adventure_ref)
        return self.adventure


class MemoryCharacterBundleStore:
    def __init__(self) -> None:
        self.saved: dict[str, tuple[PlayerCharacter, OpeningDocument]] = {}

    def save(
        self,
        campaign_id: CampaignId,
        character: PlayerCharacter,
        opening: OpeningDocument,
    ) -> str:
        self.saved[campaign_id] = (character, opening)
        return CHARACTER_REF


def step_input(language: LanguageCode) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "campaignId": CAMPAIGN_ID,
        "language": language,
        "correlationId": "corr-character-step",
        "adventureRef": ADVENTURE_REF,
        "latencyMs": 812,
    }


def clock(values: tuple[float, ...]) -> Iterator[float]:
    return iter(values)


@pytest.mark.parametrize("language", ["en", "es"])
def test_step_loads_adventure_and_persists_character_with_ordered_opening(
    language: LanguageCode,
) -> None:
    architect = FakeCharacterArchitect(sample_player())
    adventures = MemoryAdventurePlanLoader(sample_plan())
    characters = MemoryCharacterBundleStore()
    times = clock((20.0, 20.250))
    step = CharacterStep(
        architect,
        adventures,
        characters,
        monotonic=lambda: next(times),
    )

    result = step.handle(step_input(language))

    assert result == {
        "schemaVersion": 1,
        "campaignId": CAMPAIGN_ID,
        "language": language,
        "correlationId": "corr-character-step",
        "adventureRef": ADVENTURE_REF,
        "characterRef": CHARACTER_REF,
        "latencyMs": 250,
    }
    assert adventures.loaded_refs == [result["adventureRef"]]
    assert architect.calls == [(language, sample_plan())]

    character, opening = characters.saved[CAMPAIGN_ID]
    assert character.name == "Iria Vale"
    assert opening.language == language
    assert opening.title == "The Storm Bell"
    assert [block.position for block in opening.blocks] == list(range(len(opening.blocks)))
    assert [block.text for block in opening.blocks if block.kind is OpeningBlockKind.KNOWLEDGE] == (
        sample_player().known_facts
    )
    action_texts = [
        block.text for block in opening.blocks if block.kind is OpeningBlockKind.POSSIBLE_ACTION
    ]
    assert action_texts == sample_player().opening_choices
    assert all(
        not block.narratable
        for block in opening.blocks
        if block.kind is OpeningBlockKind.POSSIBLE_ACTION
    )
    serialized_opening = opening.model_dump_json()
    assert all(secret not in serialized_opening for secret in sample_plan().secrets)
    assert "character" not in result
    assert "opening" not in result


def test_step_revalidates_untrusted_character_before_persisting() -> None:
    raw_character = sample_player().model_dump(mode="python")
    raw_character["opening_choices"] = ["Only one choice"]
    invalid = PlayerCharacter.model_construct(**raw_character)
    characters = MemoryCharacterBundleStore()
    step = CharacterStep(
        FakeCharacterArchitect(invalid),
        MemoryAdventurePlanLoader(sample_plan()),
        characters,
    )

    with pytest.raises(ValidationError):
        step.handle(step_input("en"))

    assert characters.saved == {}


def test_handler_rejects_invalid_input_before_loading_adventure() -> None:
    adventures = MemoryAdventurePlanLoader(sample_plan())
    architect = FakeCharacterArchitect(sample_player())
    step = CharacterStep(architect, adventures, MemoryCharacterBundleStore())
    raw = step_input("es")
    raw["language"] = "fr"

    with pytest.raises(ValidationError):
        step.handle(raw)

    assert adventures.loaded_refs == []
    assert architect.calls == []

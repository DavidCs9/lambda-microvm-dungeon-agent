"""Generate a protagonist and a presentation-neutral opening document."""

import time
from collections.abc import Callable, Mapping
from typing import Literal, Protocol

from pydantic import Field

from dungeon_agent.control_plane.domain.base import ContractModel
from dungeon_agent.control_plane.domain.enums import OpeningBlockKind
from dungeon_agent.control_plane.domain.models import (
    CorrelationId,
    OpeningBlock,
    OpeningDocument,
    SessionId,
)
from dungeon_agent.control_plane.domain.ports import CharacterArchitectPort
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter


class AdventurePlanLoader(Protocol):
    """Load the validated adventure produced by the previous workflow step."""

    def load(self, adventure_ref: str) -> AdventurePlan: ...


class CharacterBundleStore(Protocol):
    """Persist the character and its shared visual/audio opening."""

    def save(
        self,
        session_id: SessionId,
        character: PlayerCharacter,
        opening: OpeningDocument,
    ) -> str: ...


class CharacterStepInput(ContractModel):
    """Small hand-off from the Adventure Architect step."""

    schema_version: Literal[1] = 1
    session_id: SessionId
    language: LanguageCode
    correlation_id: CorrelationId
    adventure_ref: str = Field(min_length=3, max_length=2_048)
    adventure_latency_ms: int = Field(alias="latencyMs", ge=0)


class CharacterStepResult(ContractModel):
    """Small state passed to the MicroVM initialization steps."""

    schema_version: Literal[1] = 1
    session_id: SessionId
    language: LanguageCode
    correlation_id: CorrelationId
    adventure_ref: str = Field(min_length=3, max_length=2_048)
    character_ref: str = Field(min_length=3, max_length=2_048)
    latency_ms: int = Field(ge=0)


class CharacterStep:
    """Run the Character Architect and persist its reusable opening artifact."""

    def __init__(
        self,
        architect: CharacterArchitectPort,
        adventures: AdventurePlanLoader,
        characters: CharacterBundleStore,
        *,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._architect = architect
        self._adventures = adventures
        self._characters = characters
        self._monotonic = monotonic

    def execute(self, step_input: CharacterStepInput) -> CharacterStepResult:
        started = self._monotonic()
        loaded = self._adventures.load(step_input.adventure_ref)
        adventure = AdventurePlan.model_validate(loaded.model_dump(mode="python"))
        generated = self._architect.create(step_input.language, adventure)
        character = PlayerCharacter.model_validate(generated.model_dump(mode="python"))
        opening = _build_opening(step_input.language, adventure, character)
        character_ref = self._characters.save(step_input.session_id, character, opening)
        latency_ms = max(0, round((self._monotonic() - started) * 1_000))
        return CharacterStepResult(
            session_id=step_input.session_id,
            language=step_input.language,
            correlation_id=step_input.correlation_id,
            adventure_ref=step_input.adventure_ref,
            character_ref=character_ref,
            latency_ms=latency_ms,
        )

    def handle(self, raw_input: Mapping[str, object]) -> dict[str, object]:
        """Validate wire input and return an alias-serialized workflow payload."""

        step_input = CharacterStepInput.model_validate(raw_input)
        return self.execute(step_input).model_dump(mode="json", by_alias=True)


def _build_opening(
    language: LanguageCode,
    adventure: AdventurePlan,
    character: PlayerCharacter,
) -> OpeningDocument:
    content: list[tuple[str, OpeningBlockKind, str, bool]] = [
        (
            "identity",
            OpeningBlockKind.IDENTITY,
            f"{character.name}. {character.pronouns}. {character.archetype}.",
            True,
        ),
        ("appearance", OpeningBlockKind.BACKGROUND, character.appearance, True),
        ("background", OpeningBlockKind.BACKGROUND, character.background, True),
        ("desire", OpeningBlockKind.MOTIVATION, character.desire, True),
        ("need", OpeningBlockKind.MOTIVATION, character.need, True),
        (
            "adventure_connection",
            OpeningBlockKind.BACKGROUND,
            character.connection_to_adventure,
            True,
        ),
        ("strength", OpeningBlockKind.BACKGROUND, character.strength, True),
        ("flaw", OpeningBlockKind.BACKGROUND, character.flaw, True),
        ("meaningful_item", OpeningBlockKind.BACKGROUND, character.meaningful_item, True),
    ]
    content.extend(
        (f"knowledge_{index}", OpeningBlockKind.KNOWLEDGE, fact, True)
        for index, fact in enumerate(character.known_facts, start=1)
    )
    content.append(("situation", OpeningBlockKind.SITUATION, adventure.opening, True))
    content.extend(
        (f"action_{index}", OpeningBlockKind.POSSIBLE_ACTION, action, False)
        for index, action in enumerate(character.opening_choices, start=1)
    )
    return OpeningDocument(
        language=language,
        title=adventure.title,
        blocks=tuple(
            OpeningBlock(
                id=block_id,
                position=position,
                kind=kind,
                text=text,
                narratable=narratable,
            )
            for position, (block_id, kind, text, narratable) in enumerate(content)
        ),
    )

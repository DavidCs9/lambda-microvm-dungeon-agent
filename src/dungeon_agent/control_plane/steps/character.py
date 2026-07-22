"""Generate a protagonist and a presentation-neutral opening document."""

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal, cast

from pydantic import Field

from dungeon_agent.control_plane.domain.base import ContractModel
from dungeon_agent.control_plane.domain.enums import OpeningBlockKind
from dungeon_agent.control_plane.domain.models import (
    ArtifactRef,
    CampaignId,
    CorrelationId,
    OpeningBlock,
    OpeningDocument,
)
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter

LOGGER = logging.getLogger(__name__)


class CharacterStepInput(ContractModel):
    """Small hand-off from the Adventure Architect step."""

    schema_version: Literal[1] = 1
    campaign_id: CampaignId
    language: LanguageCode
    correlation_id: CorrelationId
    adventure_ref: ArtifactRef
    adventure_latency_ms: int = Field(alias="latencyMs", ge=0)


class CharacterStepResult(ContractModel):
    """Small state passed to the campaign readiness steps."""

    schema_version: Literal[1] = 1
    campaign_id: CampaignId
    language: LanguageCode
    correlation_id: CorrelationId
    adventure_ref: ArtifactRef
    character_ref: ArtifactRef
    latency_ms: int = Field(ge=0)


class CharacterStep:
    """Run the Character Architect and persist its reusable opening artifact."""

    def __init__(
        self,
        architect: Any,
        adventures: Any,
        characters: Any,
        *,
        portrait_generator: Any | None = None,
        portrait_store: Any | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._architect = architect
        self._adventures = adventures
        self._characters = characters
        self._portrait_generator = portrait_generator
        self._portrait_store = portrait_store
        self._monotonic = monotonic

    def execute(self, step_input: CharacterStepInput) -> CharacterStepResult:
        started = self._monotonic()
        loaded = self._adventures.load(step_input.adventure_ref)
        adventure = AdventurePlan.model_validate(loaded.model_dump(mode="python"))
        generated = self._architect.create(step_input.language, adventure)
        character = PlayerCharacter.model_validate(generated.model_dump(mode="python"))
        opening = _build_opening(step_input.language, adventure, character)
        portrait_key = self._try_generate_portrait(step_input.campaign_id, character)
        character_ref = self._characters.save(
            step_input.campaign_id, character, opening, portrait_key=portrait_key
        )
        latency_ms = max(0, round((self._monotonic() - started) * 1_000))
        return CharacterStepResult(
            campaign_id=step_input.campaign_id,
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

    def _try_generate_portrait(
        self, campaign_id: CampaignId, character: PlayerCharacter
    ) -> str | None:
        """Best-effort portrait generation; never block campaign creation on failure."""

        if self._portrait_generator is None or self._portrait_store is None:
            return None
        try:
            image = self._portrait_generator.generate(character)
            return cast(str, self._portrait_store.save(campaign_id, image))
        except Exception:
            LOGGER.exception("portrait_generation_failed", extra={"campaign_id": campaign_id})
            return None


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
        ("desire", OpeningBlockKind.MOTIVATION, character.desire, True),
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

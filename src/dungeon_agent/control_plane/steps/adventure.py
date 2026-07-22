import time
from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import Field

from dungeon_agent.control_plane.domain.base import ContractModel
from dungeon_agent.control_plane.domain.models import (
    ArtifactRef,
    CampaignId,
    CorrelationId,
    CreateCampaignWorkflowInput,
)
from dungeon_agent.domain.game import AdventurePlan, LanguageCode


class AdventureStepResult(ContractModel):
    schema_version: Literal[1] = 1
    campaign_id: CampaignId
    language: LanguageCode
    correlation_id: CorrelationId
    adventure_ref: ArtifactRef
    latency_ms: int = Field(ge=0)


class AdventureStep:
    def __init__(
        self,
        architect: Any,
        plans: Any,
        *,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._architect = architect
        self._plans = plans
        self._monotonic = monotonic

    def execute(self, workflow_input: CreateCampaignWorkflowInput) -> AdventureStepResult:
        started = self._monotonic()
        generated = self._architect.create(workflow_input.language)
        adventure = AdventurePlan.model_validate(generated.model_dump(mode="python"))
        adventure_ref = self._plans.save(workflow_input.campaign_id, adventure)
        latency_ms = max(0, round((self._monotonic() - started) * 1_000))
        return AdventureStepResult(
            campaign_id=workflow_input.campaign_id,
            language=workflow_input.language,
            correlation_id=workflow_input.correlation_id,
            adventure_ref=adventure_ref,
            latency_ms=latency_ms,
        )

    def handle(self, raw_input: Mapping[str, object]) -> dict[str, object]:
        workflow_input = CreateCampaignWorkflowInput.model_validate(raw_input)
        return self.execute(workflow_input).model_dump(mode="json", by_alias=True)

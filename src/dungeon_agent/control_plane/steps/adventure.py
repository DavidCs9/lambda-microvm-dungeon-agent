"""Generate and persist an adventure without growing workflow state."""

import time
from collections.abc import Callable, Mapping
from typing import Literal, Protocol

from pydantic import Field

from dungeon_agent.control_plane.domain.base import ContractModel
from dungeon_agent.control_plane.domain.models import (
    CorrelationId,
    CreateSessionWorkflowInput,
    SessionId,
)
from dungeon_agent.control_plane.domain.ports import AdventureArchitectPort
from dungeon_agent.domain.game import AdventurePlan, LanguageCode


class AdventurePlanStore(Protocol):
    """Persist a validated plan and return its opaque location."""

    def save(self, session_id: SessionId, adventure: AdventurePlan) -> str: ...


class AdventureStepResult(ContractModel):
    """Small state passed to the next session-creation step."""

    schema_version: Literal[1] = 1
    session_id: SessionId
    language: LanguageCode
    correlation_id: CorrelationId
    adventure_ref: str = Field(min_length=3, max_length=2_048)
    latency_ms: int = Field(ge=0)


class AdventureStep:
    """Run the Adventure Architect and keep its full output out of workflow state."""

    def __init__(
        self,
        architect: AdventureArchitectPort,
        plans: AdventurePlanStore,
        *,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._architect = architect
        self._plans = plans
        self._monotonic = monotonic

    def execute(self, workflow_input: CreateSessionWorkflowInput) -> AdventureStepResult:
        started = self._monotonic()
        generated = self._architect.create(workflow_input.language)
        adventure = AdventurePlan.model_validate(generated.model_dump(mode="python"))
        adventure_ref = self._plans.save(workflow_input.session_id, adventure)
        latency_ms = max(0, round((self._monotonic() - started) * 1_000))
        return AdventureStepResult(
            session_id=workflow_input.session_id,
            language=workflow_input.language,
            correlation_id=workflow_input.correlation_id,
            adventure_ref=adventure_ref,
            latency_ms=latency_ms,
        )

    def handle(self, raw_input: Mapping[str, object]) -> dict[str, object]:
        """Validate wire input and return an alias-serialized workflow payload."""

        workflow_input = CreateSessionWorkflowInput.model_validate(raw_input)
        return self.execute(workflow_input).model_dump(mode="json", by_alias=True)

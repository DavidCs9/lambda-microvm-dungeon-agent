from collections.abc import Mapping
from typing import Protocol

from dungeon_agent.control_plane.domain.models import (
    CreateCampaignWorkflowInput,
    CreateSessionWorkflowInput,
)


class _StepFunctionsExceptions(Protocol):
    ExecutionAlreadyExists: type[Exception]


class StepFunctionsClient(Protocol):
    @property
    def exceptions(self) -> _StepFunctionsExceptions: ...

    def start_execution(self, **kwargs: object) -> Mapping[str, object]: ...


class StepFunctionsWorkflowStarter:
    def __init__(
        self,
        client: StepFunctionsClient,
        state_machine_arn: str,
        *,
        campaign_state_machine_arn: str | None = None,
    ) -> None:
        self._client = client
        self._state_machine_arn = state_machine_arn
        self._campaign_state_machine_arn = campaign_state_machine_arn

    def start_create_session(self, workflow_input: CreateSessionWorkflowInput) -> str:
        return self._start(
            self._state_machine_arn,
            workflow_input.session_id,
            workflow_input.model_dump_json(by_alias=True),
        )

    def start_create_campaign(self, workflow_input: CreateCampaignWorkflowInput) -> str:
        if self._campaign_state_machine_arn is None:
            raise RuntimeError("campaign state machine is not configured")
        return self._start(
            self._campaign_state_machine_arn,
            workflow_input.campaign_id,
            workflow_input.model_dump_json(by_alias=True),
        )

    def _start(self, state_machine_arn: str, name: str, payload: str) -> str:
        try:
            response = self._client.start_execution(
                stateMachineArn=state_machine_arn,
                name=name,
                input=payload,
            )
        except self._client.exceptions.ExecutionAlreadyExists:
            return self._execution_arn(state_machine_arn, name)
        execution_arn = response.get("executionArn")
        if not isinstance(execution_arn, str):
            raise RuntimeError("Step Functions did not return an execution ARN")
        return execution_arn

    @staticmethod
    def _execution_arn(state_machine_arn: str, name: str) -> str:
        prefix = state_machine_arn.replace(":stateMachine:", ":execution:", 1)
        return f"{prefix}:{name}"

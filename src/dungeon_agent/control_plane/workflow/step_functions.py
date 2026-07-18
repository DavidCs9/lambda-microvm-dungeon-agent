"""Amazon Step Functions workflow starter."""

from collections.abc import Mapping
from typing import Protocol

from dungeon_agent.control_plane.domain.models import CreateSessionWorkflowInput


class _StepFunctionsExceptions(Protocol):
    ExecutionAlreadyExists: type[Exception]


class StepFunctionsClient(Protocol):
    @property
    def exceptions(self) -> _StepFunctionsExceptions: ...

    def start_execution(self, **kwargs: object) -> Mapping[str, object]: ...


class StepFunctionsWorkflowStarter:
    """Start a Standard execution named after the session."""

    def __init__(self, client: StepFunctionsClient, state_machine_arn: str) -> None:
        self._client = client
        self._state_machine_arn = state_machine_arn

    def start_create_session(self, workflow_input: CreateSessionWorkflowInput) -> str:
        try:
            response = self._client.start_execution(
                stateMachineArn=self._state_machine_arn,
                name=workflow_input.session_id,
                input=workflow_input.model_dump_json(by_alias=True),
            )
        except self._client.exceptions.ExecutionAlreadyExists:
            return self._execution_arn(workflow_input.session_id)
        execution_arn = response.get("executionArn")
        if not isinstance(execution_arn, str):
            raise RuntimeError("Step Functions did not return an execution ARN")
        return execution_arn

    def _execution_arn(self, session_id: str) -> str:
        prefix = self._state_machine_arn.replace(":stateMachine:", ":execution:", 1)
        return f"{prefix}:{session_id}"

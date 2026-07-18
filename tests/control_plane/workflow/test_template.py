"""Structural checks for the deployable create-session workflow skeleton."""

from itertools import pairwise
from pathlib import Path

TEMPLATE = Path(__file__).parents[3] / "infra" / "control-plane" / "workflow" / "template.yaml"
WORKFLOW_STUB = (
    Path(__file__).parents[3] / "src" / "dungeon_agent" / "control_plane" / "workflow" / "stub.py"
)

SUCCESS_PATH = (
    "ValidateSession",
    "CreateSessionRecord",
    "EmitStartingMicrovm",
    "LaunchMicrovm",
    "WaitForMicrovm",
    "EmitCreatingAdventure",
    "GenerateAdventure",
    "PersistAdventure",
    "EmitCreatingCharacter",
    "GenerateCharacter",
    "PersistCharacter",
    "EmitInitializingGame",
    "InitializeMicrovmGame",
    "MarkSessionReady",
    "EmitSessionReady",
    "SessionCreated",
)


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _workflow_stub() -> str:
    return WORKFLOW_STUB.read_text(encoding="utf-8")


def test_workflow_is_standard_and_has_the_complete_named_success_path() -> None:
    template = _template()

    assert "StateMachineType: STANDARD" in template
    positions = [template.index(f"          {state}:") for state in SUCCESS_PATH]
    assert positions == sorted(positions)


def test_every_success_path_task_has_timeout_retry_and_failure_catch() -> None:
    template = _template()

    for current, following in pairwise(SUCCESS_PATH):
        start = template.index(f"          {current}:")
        end = template.index(f"          {following}:")
        state = template[start:end]
        assert "Type: Task" in state
        assert "TimeoutSeconds:" in state
        assert "Retry:" in state
        assert "Catch:" in state
        assert f"Next: {following}" in state


def test_validation_errors_are_caught_but_never_listed_as_retriable() -> None:
    template = _template()
    validate_state = template[template.index("          ValidateSession:") :]
    validate_state = validate_state[: validate_state.index("          CreateSessionRecord:")]
    retry = validate_state[validate_state.index("            Retry:") :]
    retry = retry[: retry.index("            Catch:")]
    catch = validate_state[validate_state.index("            Catch:") :]
    catch = catch[: catch.index("            Next: CreateSessionRecord")]

    assert "ValidationError" not in retry
    assert "AuthorizationError" not in retry
    assert "ValidationError" in catch
    assert "AuthorizationError" in catch
    assert "BackoffRate: 2.0" in retry
    assert "JitterStrategy: FULL" in retry
    assert "MaxAttempts: 3" in retry


def test_failure_path_marks_session_and_emits_failure_event_before_failing() -> None:
    template = _template()

    assert "Next: MarkSessionFailed" in template
    assert "operation: MarkSessionFailed" in template
    assert "Next: EmitSessionCreationFailed" in template
    assert "operation: EmitSessionCreationFailed" in template
    assert "EventType.SESSION_CREATION_FAILED" in _workflow_stub()
    assert "SessionCreationFailed:\n            Type: Fail" in template


def test_terminal_execution_monitoring_covers_all_abnormal_outcomes() -> None:
    template = _template()

    for status in ("FAILED", "TIMED_OUT", "ABORTED"):
        assert f"            - {status}" in template
    for metric in ("ExecutionsFailed", "ExecutionsTimedOut", "ExecutionsAborted"):
        assert f"MetricName: {metric}" in template
    assert "DeadLetterConfig:" in template
    assert "SqsManagedSseEnabled: true" in template


def test_workflow_exposes_execution_and_phase_timing_hooks_without_payload_logging() -> None:
    template = _template()

    assert 'workflowExecutionArn.$: "$$.Execution.Id"' in template
    assert 'stateEnteredAt.$: "$$.State.EnteredTime"' in template
    assert 'retryCount.$: "$$.State.RetryCount"' in template
    workflow_stub = _workflow_stub()
    assert 'state.get("phaseTimestamps", {})' in workflow_stub
    assert 'state.get("taskTimestamps", {})' in workflow_stub
    assert "IncludeExecutionData: false" in template


def test_normal_contract_input_does_not_require_failure_injection_fields() -> None:
    template = _template()

    assert "forceValidationFailureAt.$" not in template
    assert "forceAuthorizationFailureAt.$" not in template
    assert "forceRetriableFailureAt.$" not in template
    assert "forceRetriableAttempts.$" not in template
    assert "CreateSessionWorkflowInput.model_validate(raw_state)" in _workflow_stub()

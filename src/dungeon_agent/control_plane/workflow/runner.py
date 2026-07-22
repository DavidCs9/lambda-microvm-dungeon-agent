from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Self

from dungeon_agent.control_plane.workflow.util import parse_time, required_string, wire_time

Clock = Callable[[], datetime]


class WorkflowRecord(Protocol):
    revision: int

    def model_copy(self, *, update: Mapping[str, object]) -> Self: ...


class RecordModel[RecordT: WorkflowRecord](Protocol):
    def model_validate(self, obj: Any) -> RecordT: ...


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    operation: str
    state: dict[str, object]
    now: datetime
    workflow_arn: str
    entered_at: datetime


def prepare_run(
    event: Mapping[str, object],
    clock: Clock,
    *,
    validate: Callable[[Mapping[str, object]], Any] | None = None,
) -> WorkflowRun:
    operation = required_string(event, "operation")
    raw_state = event.get("state")
    if not isinstance(raw_state, Mapping):
        raise ValueError("workflow state must be an object")
    if validate is not None:
        validate(raw_state)

    now = clock()
    entered_at = parse_time(required_string(event, "stateEnteredAt"))
    state = dict(raw_state)
    state["workflowExecutionArn"] = workflow_arn = required_string(event, "workflowExecutionArn")
    state["updatedAt"] = wire_time(now)
    timestamps = dict(state.get("taskTimestamps", {}))
    timestamps[operation] = {
        "startedAt": wire_time(entered_at),
        "completedAt": wire_time(now),
    }
    state["taskTimestamps"] = timestamps
    return WorkflowRun(operation, state, now, workflow_arn, entered_at)


def required_record[T: WorkflowRecord](
    store: Any,
    state: Mapping[str, object],
    model: RecordModel[T],
    id_key: str,
    name: str,
) -> T:
    record_id = required_string(state, id_key)
    record = store.get(record_id)
    if record is None:
        raise ValueError(f"{name} does not exist: {record_id}")
    return model.model_validate(record)


def update_record[T: WorkflowRecord](
    store: Any,
    state: Mapping[str, object],
    model: RecordModel[T],
    id_key: str,
    name: str,
    clock: Clock,
    workflow_arn: str,
    **updates: object,
) -> T:
    current = required_record(store, state, model, id_key, name)
    patch = {key: value for key, value in updates.items() if value is not None}
    patch.update(
        workflow_execution_arn=workflow_arn,
        revision=current.revision + 1,
        updated_at=clock(),
    )
    saved = store.save(
        model.model_validate(current.model_copy(update=patch)),
        expected_revision=current.revision,
    )
    return model.model_validate(saved)


def mark_phase(state: dict[str, object], phase: Any, entered_at: datetime) -> None:
    timestamps = state.get("phaseTimestamps", {})
    phase_timestamps = dict(timestamps) if isinstance(timestamps, Mapping) else {}
    phase_timestamps[phase.value] = wire_time(entered_at)
    state["phaseTimestamps"] = phase_timestamps
    state["phase"] = phase.value


def elapsed_ms(now: datetime, started_at: datetime) -> int:
    return max(0, int((now - started_at).total_seconds() * 1_000))

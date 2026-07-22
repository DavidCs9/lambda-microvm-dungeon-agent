from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dungeon_agent.control_plane.workflow.util import parse_time, required_string, wire_time

Clock = Callable[[], datetime]


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

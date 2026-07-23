from collections.abc import Callable
from datetime import datetime
from typing import Any


def ensure_workflow(
    record: Any,
    *,
    store: Any,
    aggregate_id: str,
    now: datetime,
    start: Callable[[], str],
) -> Any:
    if record.workflow_execution_arn is not None:
        return record
    updated = record.model_copy(
        update={
            "workflow_execution_arn": start(),
            "revision": record.revision + 1,
            "updated_at": now,
        }
    )
    try:
        return type(record).model_validate(store.save(updated, expected_revision=record.revision))
    except Exception:
        current = store.get(aggregate_id)
        if current is not None and current.workflow_execution_arn is not None:
            return type(record).model_validate(current)
        raise

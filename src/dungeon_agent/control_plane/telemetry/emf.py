import json
from collections.abc import Callable
from datetime import UTC, datetime

Metric = tuple[str, str, int | float]


class EmfTelemetry:
    def __init__(
        self,
        service: str,
        *,
        namespace: str = "DungeonAgent/Lab",
        sink: Callable[[str], None] = print,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = _required(service, "service")
        self._namespace = _required(namespace, "namespace")
        self._sink = sink
        self._clock = clock or (lambda: datetime.now(UTC))

    def phase(
        self,
        operation: str,
        outcome: str,
        latency_ms: int | float,
        **context: str | None,
    ) -> dict[str, object]:
        return self._emit(
            operation,
            outcome,
            (("PhaseLatencyMs", "Milliseconds", _non_negative(latency_ms, "latency_ms")),),
            context,
        )

    def model(
        self,
        operation: str,
        outcome: str,
        *,
        latency_ms: int | float,
        input_tokens: int,
        output_tokens: int,
        **context: str | None,
    ) -> dict[str, object]:
        return self._emit(
            operation,
            outcome,
            (
                ("ModelLatencyMs", "Milliseconds", _non_negative(latency_ms, "latency_ms")),
                ("InputTokens", "Count", _non_negative(input_tokens, "input_tokens")),
                ("OutputTokens", "Count", _non_negative(output_tokens, "output_tokens")),
            ),
            context,
        )

    def microvm(
        self,
        operation: str,
        outcome: str,
        latency_ms: int | float,
        **context: str | None,
    ) -> dict[str, object]:
        return self._emit(
            operation,
            outcome,
            (("MicrovmLatencyMs", "Milliseconds", _non_negative(latency_ms, "latency_ms")),),
            context,
        )

    def _emit(
        self,
        operation: str,
        outcome: str,
        metrics: tuple[Metric, ...],
        context: dict[str, str | None],
    ) -> dict[str, object]:
        operation = _required(operation, "operation")
        outcome = _required(outcome, "outcome")
        dimensions = ["Service", "Operation", "Outcome"]
        record: dict[str, object] = {
            "_aws": {
                "Timestamp": round(self._clock().timestamp() * 1_000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": [dimensions],
                        "Metrics": [
                            {"Name": name, "Unit": unit, "StorageResolution": 60}
                            for name, unit, _value in metrics
                        ],
                    }
                ],
            },
            "Service": self._service,
            "Operation": operation,
            "Outcome": outcome,
        }
        record.update({name: value for name, _unit, value in metrics})
        record.update(
            {
                wire_name: value
                for wire_name, value in (
                    ("sessionId", context.get("session_id")),
                    ("playerId", context.get("player_id")),
                    ("correlationId", context.get("correlation_id")),
                )
                if value is not None
            }
        )
        self._sink(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        return record


def _required(value: str, field: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")
    return value


def _non_negative(value: int | float, field: str) -> int | float:
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value

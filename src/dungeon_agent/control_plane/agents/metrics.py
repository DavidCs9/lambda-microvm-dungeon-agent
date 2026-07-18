"""Observability port required by model adapters."""

from typing import Protocol


class AgentMetricsPort(Protocol):
    def record(self, *, input_tokens: int, output_tokens: int, latency_ms: float) -> None: ...

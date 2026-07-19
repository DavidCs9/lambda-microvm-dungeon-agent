"""Observability port required by model adapters."""

from typing import Protocol

from dungeon_agent.control_plane.domain.models import RoleGenerationMetrics


class AgentMetricsPort(Protocol):
    def record(self, *, input_tokens: int, output_tokens: int, latency_ms: float) -> None: ...


class RoleMetricsCollector:
    """Aggregate one role's model usage so it can persist on the campaign record.

    A collector is wired into a long-lived Lambda environment, so callers must
    ``reset()`` it when a campaign workflow starts; without the reset a warm
    instance would leak usage from a previous campaign.
    """

    def __init__(self, sink: AgentMetricsPort | None = None) -> None:
        self._sink = sink
        self.reset()

    def reset(self) -> None:
        self._calls = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._latency_ms = 0.0

    def record(self, *, input_tokens: int, output_tokens: int, latency_ms: float) -> None:
        self._calls += 1
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._latency_ms += latency_ms
        if self._sink is not None:
            self._sink.record(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )

    def snapshot(self, model_id: str) -> RoleGenerationMetrics:
        """Summarize the role; every call after the first is an output repair."""
        return RoleGenerationMetrics(
            model_id=model_id,
            calls=self._calls,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            latency_ms=max(0, round(self._latency_ms)),
            repairs=max(0, self._calls - 1),
        )

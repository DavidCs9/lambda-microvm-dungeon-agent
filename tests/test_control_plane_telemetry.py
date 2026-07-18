import json
from datetime import UTC, datetime

import pytest

from dungeon_agent.control_plane.telemetry import EmfTelemetry

NOW = datetime(2026, 7, 18, 12, 30, tzinfo=UTC)


def telemetry(output: list[str]) -> EmfTelemetry:
    return EmfTelemetry(
        "session-creation",
        sink=output.append,
        clock=lambda: NOW,
    )


def metric_names(record: dict[str, object]) -> list[str]:
    aws = record["_aws"]
    assert isinstance(aws, dict)
    directives = aws["CloudWatchMetrics"]
    assert isinstance(directives, list)
    directive = directives[0]
    assert isinstance(directive, dict)
    metrics = directive["Metrics"]
    assert isinstance(metrics, list)
    return [metric["Name"] for metric in metrics if isinstance(metric, dict)]


def test_phase_emits_valid_low_cardinality_emf_and_json_context() -> None:
    output: list[str] = []

    record = telemetry(output).phase(
        "GenerateCharacter",
        "success",
        825,
        session_id="ses_demo",
        player_id="player_demo",
        correlation_id="corr_demo",
    )

    aws = record["_aws"]
    assert isinstance(aws, dict)
    assert aws["Timestamp"] == round(NOW.timestamp() * 1_000)
    directives = aws["CloudWatchMetrics"]
    assert isinstance(directives, list)
    directive = directives[0]
    assert isinstance(directive, dict)
    assert directive["Namespace"] == "DungeonAgent/Lab"
    assert directive["Dimensions"] == [["Service", "Operation", "Outcome"]]
    assert record["PhaseLatencyMs"] == 825
    assert record["sessionId"] == "ses_demo"
    assert record["playerId"] == "player_demo"
    assert record["correlationId"] == "corr_demo"
    assert json.loads(output[0]) == record


def test_model_records_tokens_and_latency_without_content() -> None:
    output: list[str] = []

    record = telemetry(output).model(
        "CharacterArchitect",
        "success",
        latency_ms=1_250.5,
        input_tokens=2_100,
        output_tokens=430,
        session_id="ses_demo",
    )

    assert metric_names(record) == ["ModelLatencyMs", "InputTokens", "OutputTokens"]
    assert record["ModelLatencyMs"] == 1_250.5
    assert record["InputTokens"] == 2_100
    assert record["OutputTokens"] == 430
    assert "prompt" not in output[0]
    assert "response" not in output[0]


@pytest.mark.parametrize(
    "operation",
    ["LaunchMicrovm", "WaitForMicrovm", "InitializeMicrovm", "TerminateMicrovm"],
)
def test_microvm_records_each_lifecycle_timing(operation: str) -> None:
    record = telemetry([]).microvm(operation, "success", 300)

    assert metric_names(record) == ["MicrovmLatencyMs"]
    assert record["MicrovmLatencyMs"] == 300
    assert record["Operation"] == operation


def test_rejects_negative_metrics_before_writing() -> None:
    output: list[str] = []
    emitter = telemetry(output)

    with pytest.raises(ValueError, match="input_tokens must be non-negative"):
        emitter.model(
            "AdventureArchitect",
            "failure",
            latency_ms=10,
            input_tokens=-1,
            output_tokens=0,
        )

    assert output == []

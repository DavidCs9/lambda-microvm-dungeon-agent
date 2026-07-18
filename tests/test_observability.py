import json
from decimal import Decimal
from pathlib import Path

from dungeon_agent.orchestrator.observability import SessionMetrics, load_model_price


def test_nova_micro_session_cost_uses_external_pricing() -> None:
    metrics = SessionMetrics.start("us.amazon.nova-micro-v1:0")
    metrics.record(input_tokens=1_000_000, output_tokens=1_000_000, latency_ms=500)

    assert metrics.estimated_cost == Decimal("0.175")
    assert metrics.total_tokens == 2_000_000
    assert load_model_price(metrics.model_id) is not None


def test_unknown_model_cost_is_unavailable() -> None:
    metrics = SessionMetrics.start("unknown-model")
    metrics.record(input_tokens=10, output_tokens=5, latency_ms=25)

    assert metrics.estimated_cost is None


def test_session_metrics_append_privacy_safe_jsonl(tmp_path: Path) -> None:
    metrics = SessionMetrics.start("us.amazon.nova-micro-v1:0")
    metrics.record(input_tokens=100, output_tokens=20, latency_ms=125.5)
    output = tmp_path / "metrics" / "sessions.jsonl"

    metrics.append_jsonl(output)

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["session_id"] == metrics.session_id
    assert record["total_tokens"] == 120
    assert record["estimated_cost_usd"] == "0.00000630"
    assert "prompt" not in record
    assert "narration" not in record

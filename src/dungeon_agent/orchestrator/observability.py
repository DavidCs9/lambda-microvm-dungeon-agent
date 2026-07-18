import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: Decimal
    output_per_million: Decimal
    currency: str
    source: str
    verified_at: str


def load_model_price(model_id: str) -> ModelPrice | None:
    resource = files("dungeon_agent.resources").joinpath("model_pricing.json")
    document = json.loads(resource.read_text(encoding="utf-8"))
    prices = document.get("pricesPerMillionTokens", {})
    model = prices.get(model_id) if isinstance(prices, dict) else None
    if not isinstance(model, dict):
        return None
    return ModelPrice(
        input_per_million=Decimal(str(model["input"])),
        output_per_million=Decimal(str(model["output"])),
        currency=str(document["currency"]),
        source=str(document["source"]),
        verified_at=str(document["verifiedAt"]),
    )


@dataclass
class SessionMetrics:
    model_id: str
    session_id: str
    started_at: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_latency_ms: float = 0.0

    @classmethod
    def start(cls, model_id: str) -> SessionMetrics:
        return cls(
            model_id=model_id,
            session_id=str(uuid4()),
            started_at=datetime.now(UTC).isoformat(),
        )

    def record(self, *, input_tokens: int, output_tokens: int, latency_ms: float) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.model_latency_ms += latency_ms

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost(self) -> Decimal | None:
        price = load_model_price(self.model_id)
        if price is None:
            return None
        return (
            Decimal(self.input_tokens) * price.input_per_million
            + Decimal(self.output_tokens) * price.output_per_million
        ) / Decimal(1_000_000)

    def snapshot(self) -> dict[str, object]:
        cost = self.estimated_cost
        return {
            **asdict(self),
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": format(cost, ".8f") if cost is not None else None,
            "ended_at": datetime.now(UTC).isoformat(),
        }

    def append_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(self.snapshot(), separators=(",", ":")) + "\n")

import json
import time
from dataclasses import dataclass

from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

from dungeon_agent.orchestrator.locales import Locale


@dataclass(frozen=True)
class NarrationResult:
    text: str
    latency_ms: float
    input_tokens: int
    output_tokens: int


class BedrockNarrator:
    """Generate bounded narration through the Bedrock Converse API."""

    def __init__(self, client: BedrockRuntimeClient, model_id: str, locale: Locale) -> None:
        self.client = client
        self.model_id = model_id
        self.locale = locale

    def narrate(self, action: str, world: dict[str, object]) -> str:
        return self.narrate_with_metrics(action, world).text

    def narrate_with_metrics(self, action: str, world: dict[str, object]) -> NarrationResult:
        prompt = json.dumps(
            {"latestPlayerAction": action, "currentWorldState": world},
            separators=(",", ":"),
        )
        started = time.perf_counter()
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": self.locale.system_prompt}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 180, "temperature": 0.7, "topP": 0.9},
            requestMetadata={"project": "lambda-microvm-dungeon-agent"},
        )
        if response["stopReason"] not in {"end_turn", "stop_sequence"}:
            raise RuntimeError(f"Bedrock stopped narration with {response['stopReason']}")
        content = response["output"]["message"]["content"]
        narration = "".join(block["text"] for block in content if "text" in block).strip()
        if not narration:
            raise RuntimeError("Bedrock returned an empty narration")
        usage = response["usage"]
        return NarrationResult(
            text=narration,
            latency_ms=(time.perf_counter() - started) * 1_000,
            input_tokens=usage["inputTokens"],
            output_tokens=usage["outputTokens"],
        )

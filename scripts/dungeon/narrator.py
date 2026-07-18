import json

from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

from scripts.dungeon.locales import Locale


class BedrockNarrator:
    """Generate bounded narration through the Bedrock Converse API."""

    def __init__(self, client: BedrockRuntimeClient, model_id: str, locale: Locale) -> None:
        self.client = client
        self.model_id = model_id
        self.locale = locale

    def narrate(self, action: str, world: dict[str, object]) -> str:
        prompt = json.dumps(
            {"latestPlayerAction": action, "currentWorldState": world},
            separators=(",", ":"),
        )
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
        return narration

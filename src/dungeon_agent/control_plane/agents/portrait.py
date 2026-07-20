"""Bedrock text-to-image generation for one portrait per player character."""

import base64
import json
from typing import Any, Protocol

from dungeon_agent.domain.game import PlayerCharacter

# Nova Canvas is Legacy and blocked after inactivity; Stable Image Core is Active in us-west-2.
DEFAULT_IMAGE_MODEL_ID = "stability.stable-image-core-v1:1"
DEFAULT_IMAGE_REGION = "us-west-2"
PORTRAIT_STYLE = "moody candlelit oil painting, dark brown and ember tones"
PORTRAIT_NEGATIVE_PROMPT = "text, watermark, signature, extra limbs, blurry, cartoon"


class BedrockImageRuntimePort(Protocol):
    def invoke_model(self, *, modelId: str, body: str, accept: str, contentType: str) -> Any: ...


def build_portrait_prompt(character: PlayerCharacter) -> str:
    """Describe one bust portrait in English regardless of the campaign language."""
    return (
        "Dark oil-painting fantasy portrait, bust, no text. "
        f"Subject: {character.name}, {character.pronouns}, a {character.archetype}. "
        f"Appearance: {character.appearance} "
        f"Style: {PORTRAIT_STYLE}."
    )


def generate_character_portrait(
    bedrock_client: BedrockImageRuntimePort,
    character: PlayerCharacter,
    *,
    model_id: str = DEFAULT_IMAGE_MODEL_ID,
) -> bytes:
    """Call Bedrock Stable Image Core and return the decoded PNG bytes."""
    body = json.dumps(
        {
            "prompt": build_portrait_prompt(character),
            "negative_prompt": PORTRAIT_NEGATIVE_PROMPT,
            "mode": "text-to-image",
            "aspect_ratio": "1:1",
            "output_format": "png",
        }
    )
    response = bedrock_client.invoke_model(
        modelId=model_id,
        body=body,
        accept="application/json",
        contentType="application/json",
    )
    payload = json.loads(response["body"].read())
    finish_reasons = payload.get("finish_reasons") or []
    if finish_reasons and finish_reasons[0] is not None:
        raise RuntimeError(f"Bedrock image generation filtered: {finish_reasons[0]}")
    images = payload.get("images")
    if not images:
        raise RuntimeError("Bedrock image generation returned no images")
    return base64.b64decode(images[0])


class BedrockPortraitGenerator:
    """Adapt a raw bedrock-runtime client to the CharacterStep portrait port."""

    def __init__(self, client: Any, model_id: str = DEFAULT_IMAGE_MODEL_ID) -> None:
        self._client = client
        self._model_id = model_id

    def generate(self, character: PlayerCharacter) -> bytes:
        return generate_character_portrait(self._client, character, model_id=self._model_id)

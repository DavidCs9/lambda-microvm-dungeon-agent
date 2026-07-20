import base64
import json

from dungeon_agent.control_plane.agents.portrait import (
    build_portrait_prompt,
    generate_character_portrait,
)
from dungeon_agent.control_plane.steps.portraits import portrait_object_key
from tests.test_adventure import sample_player


def test_portrait_object_key_is_campaign_scoped() -> None:
    assert portrait_object_key("cam_test") == "portraits/cam_test.png"


def test_build_portrait_prompt_uses_character_fields() -> None:
    prompt = build_portrait_prompt(sample_player())
    assert "Iria Vale" in prompt
    assert "Disgraced bell keeper" in prompt
    assert "oil-painting" in prompt.lower()


class FakeBedrockImageClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, str]] = []

    def invoke_model(
        self, *, modelId: str, body: str, accept: str, contentType: str
    ) -> dict[str, object]:
        self.calls.append(
            {"modelId": modelId, "body": body, "accept": accept, "contentType": contentType}
        )
        return {"body": _Body(json.dumps(self.payload))}


class _Body:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> bytes:
        return self._text.encode()


def test_generate_character_portrait_decodes_base64_image() -> None:
    png = b"\x89PNG\r\n\x1a\n"
    client = FakeBedrockImageClient(
        {"images": [base64.b64encode(png).decode()], "finish_reasons": [None]}
    )

    result = generate_character_portrait(client, sample_player())

    assert result == png
    assert client.calls[0]["modelId"] == "stability.stable-image-core-v1:1"
    body = json.loads(client.calls[0]["body"])
    assert body["mode"] == "text-to-image"
    assert body["aspect_ratio"] == "1:1"
    assert body["output_format"] == "png"
    assert "Iria Vale" in body["prompt"]
    assert "watermark" in body["negative_prompt"]


def test_generate_character_portrait_rejects_filtered_finish_reason() -> None:
    client = FakeBedrockImageClient({"images": [], "finish_reasons": ["Filter reason: prompt"]})
    try:
        generate_character_portrait(client, sample_player())
    except RuntimeError as exc:
        assert "filtered" in str(exc).lower()
    else:
        raise AssertionError("expected RuntimeError for filtered finish reason")

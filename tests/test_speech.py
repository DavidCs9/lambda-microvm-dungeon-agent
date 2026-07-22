import io
from typing import ClassVar

from dungeon_agent.audio.polly import (
    DEFAULT_VOICES,
    S3PollySpeechSynthesizer,
    speech_cache_key,
    speech_content_digest,
)
from dungeon_agent.control_plane.http.api_gateway import ApiGatewayHttpAdapter
from dungeon_agent.control_plane.http.campaigns import CampaignHttpHandlers
from dungeon_agent.control_plane.http.sessions import SessionHttpHandlers
from dungeon_agent.control_plane.http.speech import SpeechHttpHandlers
from dungeon_agent.control_plane.persistence.memory import (
    InMemoryCampaignRepository,
    InMemoryControlPlaneRepository,
)
from tests.test_control_plane_http import (
    CAMPAIGN_ID,
    NOW,
    FakeMicrovmManager,
    FakeOpeningLoader,
    FakeWorkflowStarter,
    _body,
    _event,
    _put_campaign,
    ready_campaign,
)


class FakeNotFoundError(Exception):
    response: ClassVar[dict[str, dict[str, str]]] = {"Error": {"Code": "404"}}


class FakePollyClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def synthesize_speech(self, **request: object) -> dict[str, object]:
        self.calls.append(request)
        return {"AudioStream": io.BytesIO(b"synthetic-audio")}


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[tuple[str, bytes]] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if Key not in self.objects:
            raise FakeNotFoundError
        return {}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
    ) -> None:
        self.put_calls.append((Key, Body))
        self.objects[Key] = Body

    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: dict[str, str],
        ExpiresIn: int,
    ) -> str:
        return f"https://fake-s3.example/{Params['Key']}?expires={ExpiresIn}"


def _speech_adapter() -> tuple[ApiGatewayHttpAdapter, FakePollyClient, FakeS3Client]:
    sessions = InMemoryControlPlaneRepository()
    workflows = FakeWorkflowStarter()
    campaigns = InMemoryCampaignRepository()
    _put_campaign(campaigns, ready_campaign())
    polly = FakePollyClient()
    s3 = FakeS3Client()
    synthesizer = S3PollySpeechSynthesizer(
        polly,
        s3,
        "speech-cache-bucket",
        DEFAULT_VOICES,
    )
    handlers = SessionHttpHandlers(
        sessions,
        workflows,
        campaigns,
        microvms=FakeMicrovmManager(),
        clock=lambda: NOW,
        session_id_factory=lambda: "ses_01J00000000000000000000000",
    )
    campaign_handlers = CampaignHttpHandlers(
        campaigns,
        workflows,
        openings=FakeOpeningLoader(),
        clock=lambda: NOW,
        campaign_id_factory=lambda: CAMPAIGN_ID,
    )
    speech = SpeechHttpHandlers(synthesizer)
    adapter = ApiGatewayHttpAdapter(
        handlers,
        campaign_handlers,
        speech=speech,
        allow_sandbox_identity=True,
    )
    return adapter, polly, s3


def test_speech_requires_authentication() -> None:
    adapter, _, _ = _speech_adapter()

    response = adapter(
        _event("POST /speech", owner=None, body={"text": "Hello.", "language": "en"})
    )

    assert response["statusCode"] == 401
    assert _body(response)["error"]["code"] == "not_authenticated"


def test_speech_rejects_empty_text() -> None:
    adapter, polly, s3 = _speech_adapter()

    response = adapter(_event("POST /speech", body={"text": "", "language": "en"}))

    assert response["statusCode"] == 400
    assert _body(response)["error"]["code"] == "validation_failed"
    assert polly.calls == []
    assert s3.put_calls == []


def test_speech_rejects_oversize_text() -> None:
    adapter, polly, s3 = _speech_adapter()

    response = adapter(_event("POST /speech", body={"text": "x" * 4001, "language": "en"}))

    assert response["statusCode"] == 400
    assert _body(response)["error"]["code"] == "validation_failed"
    assert polly.calls == []
    assert s3.put_calls == []


def test_speech_happy_path_caches_by_content_hash() -> None:
    adapter, polly, s3 = _speech_adapter()
    event = _event("POST /speech", body={"text": "The door opens.", "language": "en"})

    first = adapter(event)
    second = adapter(event)

    assert first["statusCode"] == second["statusCode"] == 200
    first_body = _body(first)
    second_body = _body(second)
    assert first_body["version"] == 1
    assert first_body["cacheHit"] is False
    assert second_body["cacheHit"] is True
    assert first_body["expiresInSeconds"] == 300
    assert first_body["url"].startswith("https://fake-s3.example/speech/")
    assert first_body["url"] == second_body["url"]
    assert len(polly.calls) == 1
    assert polly.calls[0]["Engine"] == "generative"
    assert polly.calls[0]["VoiceId"] == "Matthew"
    assert len(s3.put_calls) == 1
    key, body = s3.put_calls[0]
    assert body == b"synthetic-audio"
    digest = speech_content_digest(
        engine="generative",
        voice="Matthew",
        language="en",
        text="The door opens.",
    )
    assert key == speech_cache_key(digest)


def test_speech_without_handler_returns_dependency_error() -> None:
    adapter, _, _ = _speech_adapter()
    adapter._speech = None

    response = adapter(_event("POST /speech", body={"text": "Hello.", "language": "en"}))

    assert response["statusCode"] == 503
    assert _body(response)["error"]["code"] == "dependency_unavailable"


def test_speech_accepts_sandbox_identity_header() -> None:
    adapter, polly, _ = _speech_adapter()

    response = adapter(
        _event(
            "POST /speech",
            owner=None,
            body={"text": "Hola.", "language": "es"},
            headers={"x-player-id": "sandbox_player_001"},
        )
    )

    assert response["statusCode"] == 200
    assert _body(response)["cacheHit"] is False
    assert len(polly.calls) == 1
    assert polly.calls[0]["VoiceId"] == "Andres"

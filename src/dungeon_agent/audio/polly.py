import hashlib
from contextlib import closing
from pathlib import Path
from typing import Protocol

from mypy_boto3_polly import PollyClient
from mypy_boto3_polly.literals import EngineType, VoiceIdType

from dungeon_agent.api.models import LanguageCode

DEFAULT_VOICES: dict[LanguageCode, VoiceIdType] = {"en": "Matthew", "es": "Andres"}


def speech_content_digest(
    *,
    engine: str,
    voice: str,
    language: LanguageCode,
    text: str,
) -> str:
    return hashlib.sha256(f"{engine}\0{voice}\0{language}\0{text}".encode()).hexdigest()


def speech_cache_key(digest: str) -> str:
    return f"speech/{digest}.mp3"


class S3ClientProtocol(Protocol):
    def head_object(self, *, Bucket: str, Key: str) -> object: ...

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
    ) -> object: ...

    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: dict[str, str],
        ExpiresIn: int,
    ) -> str: ...


class PollySpeechSynthesizer:
    """Cache short bilingual narration synthesized by Amazon Polly."""

    def __init__(
        self,
        client: PollyClient,
        cache_dir: Path,
        voices: dict[LanguageCode, VoiceIdType],
        engine: EngineType = "generative",
    ) -> None:
        self.client = client
        self.cache_dir = cache_dir
        self.voices = voices
        self.engine = engine

    def synthesize(self, text: str, language: LanguageCode) -> str:
        voice = self.voices[language]
        digest = speech_content_digest(
            engine=self.engine,
            voice=voice,
            language=language,
            text=text,
        )
        output = self.cache_dir / f"{digest}.mp3"
        if output.is_file():
            return str(output)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        audio = _synthesize_mp3(
            self.client, text=text, language=language, voice=voice, engine=self.engine
        )
        temporary = output.with_suffix(".tmp")
        temporary.write_bytes(audio)
        temporary.replace(output)
        return str(output)


class S3PollySpeechSynthesizer:
    """Cache Polly narration in S3 and return presigned playback URLs."""

    def __init__(
        self,
        polly_client: PollyClient,
        s3_client: S3ClientProtocol,
        bucket: str,
        voices: dict[LanguageCode, VoiceIdType],
        *,
        engine: EngineType = "generative",
        expires_in_seconds: int = 300,
    ) -> None:
        self.polly_client = polly_client
        self.s3_client = s3_client
        self.bucket = bucket
        self.voices = voices
        self.engine = engine
        self.expires_in_seconds = expires_in_seconds

    def synthesize(self, text: str, language: LanguageCode) -> tuple[str, bool]:
        voice = self.voices[language]
        digest = speech_content_digest(
            engine=self.engine,
            voice=voice,
            language=language,
            text=text,
        )
        key = speech_cache_key(digest)
        if _s3_object_exists(self.s3_client, self.bucket, key):
            return self._presigned_url(key), True

        audio = _synthesize_mp3(
            self.polly_client,
            text=text,
            language=language,
            voice=voice,
            engine=self.engine,
        )
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=audio,
            ContentType="audio/mpeg",
        )
        return self._presigned_url(key), False

    def _presigned_url(self, key: str) -> str:
        return self.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.expires_in_seconds,
        )


def _synthesize_mp3(
    client: PollyClient,
    *,
    text: str,
    language: LanguageCode,
    voice: VoiceIdType,
    engine: EngineType,
) -> bytes:
    response = client.synthesize_speech(
        Engine=engine,
        LanguageCode="es-MX" if language == "es" else "en-US",
        OutputFormat="mp3",
        Text=text,
        TextType="text",
        VoiceId=voice,
    )
    stream = response.get("AudioStream")
    if stream is None:
        raise RuntimeError("Amazon Polly returned no audio stream")
    with closing(stream):
        return stream.read()


def _s3_object_exists(client: S3ClientProtocol, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as error:
        code = getattr(error, "response", {}).get("Error", {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True

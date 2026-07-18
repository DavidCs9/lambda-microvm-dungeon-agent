import hashlib
from contextlib import closing
from pathlib import Path

from mypy_boto3_polly import PollyClient
from mypy_boto3_polly.literals import EngineType, VoiceIdType

from dungeon_agent.api.models import LanguageCode


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
        digest = hashlib.sha256(f"{self.engine}\0{voice}\0{language}\0{text}".encode()).hexdigest()
        output = self.cache_dir / f"{digest}.mp3"
        if output.is_file():
            return str(output)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        response = self.client.synthesize_speech(
            Engine=self.engine,
            LanguageCode="es-MX" if language == "es" else "en-US",
            OutputFormat="mp3",
            Text=text,
            TextType="text",
            VoiceId=voice,
        )
        stream = response.get("AudioStream")
        if stream is None:
            raise RuntimeError("Amazon Polly returned no audio stream")
        temporary = output.with_suffix(".tmp")
        with closing(stream):
            temporary.write_bytes(stream.read())
        temporary.replace(output)
        return str(output)

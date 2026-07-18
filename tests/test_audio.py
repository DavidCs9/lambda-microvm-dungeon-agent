import io
import wave
from pathlib import Path
from typing import cast

from mypy_boto3_polly import PollyClient

from dungeon_agent.api.models import LanguageCode
from dungeon_agent.audio.local import LocalAudioExperience
from dungeon_agent.audio.polly import PollySpeechSynthesizer


class FakePollyClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def synthesize_speech(self, **request: object) -> dict[str, object]:
        self.calls.append(request)
        return {"AudioStream": io.BytesIO(b"synthetic-audio")}


class FakeSynthesizer:
    def synthesize(self, text: str, language: LanguageCode) -> str:
        raise AssertionError("voice is disabled in this test")


def test_polly_speech_is_cached_by_content(tmp_path: Path) -> None:
    client = FakePollyClient()
    synthesizer = PollySpeechSynthesizer(
        cast(PollyClient, client),
        tmp_path,
        {"en": "Matthew", "es": "Andres"},
    )

    first = synthesizer.synthesize("The door opens.", "en")
    second = synthesizer.synthesize("The door opens.", "en")

    assert first == second
    assert Path(first).read_bytes() == b"synthetic-audio"
    assert len(client.calls) == 1
    assert client.calls[0]["Engine"] == "generative"
    assert client.calls[0]["VoiceId"] == "Matthew"


def test_original_ambience_is_a_valid_loopable_wave(tmp_path: Path) -> None:
    audio = LocalAudioExperience(
        FakeSynthesizer(),
        tmp_path,
        voice_enabled=False,
        music_enabled=False,
    )

    output = audio._create_ambience()

    with wave.open(str(output), "rb") as ambience:
        assert ambience.getnchannels() == 1
        assert ambience.getframerate() == 22_050
        assert ambience.getnframes() == 22_050 * 12


def test_original_dice_roll_is_a_valid_short_wave(tmp_path: Path) -> None:
    audio = LocalAudioExperience(
        FakeSynthesizer(),
        tmp_path,
        voice_enabled=False,
        music_enabled=False,
    )

    output = audio._create_dice_sound()

    with wave.open(str(output), "rb") as dice:
        assert dice.getnchannels() == 1
        assert dice.getframerate() == 22_050
        assert dice.getnframes() == round(22_050 * 0.9)

from typing import Protocol

from dungeon_agent.api.models import LanguageCode


class AudioPort(Protocol):
    """Audio operations exposed to presentation clients."""

    @property
    def voice_enabled(self) -> bool: ...

    @property
    def music_enabled(self) -> bool: ...

    def start(self) -> None: ...

    def narrate(self, text: str, language: LanguageCode) -> None: ...

    def toggle_voice(self) -> bool: ...

    def toggle_music(self) -> bool: ...

    def stop(self) -> None: ...


class SpeechSynthesizer(Protocol):
    """Convert narration text to a locally playable audio file."""

    def synthesize(self, text: str, language: LanguageCode) -> str: ...


class SilentAudio:
    """No-op audio adapter for tests, plain mode, and unsupported hosts."""

    @property
    def voice_enabled(self) -> bool:
        return False

    @property
    def music_enabled(self) -> bool:
        return False

    def start(self) -> None:
        return None

    def narrate(self, text: str, language: LanguageCode) -> None:
        return None

    def toggle_voice(self) -> bool:
        return False

    def toggle_music(self) -> bool:
        return False

    def stop(self) -> None:
        return None

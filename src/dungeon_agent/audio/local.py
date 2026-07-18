import math
import shutil
import struct
import subprocess
import threading
import wave
from pathlib import Path

from dungeon_agent.api.models import LanguageCode
from dungeon_agent.audio.contracts import SpeechSynthesizer


class SubprocessAudioPlayer:
    """Launch a supported host audio player without invoking a shell."""

    def __init__(self) -> None:
        self.command = self._find_command()

    @staticmethod
    def _find_command() -> str | None:
        for command in ("afplay", "ffplay", "paplay", "aplay"):
            path = shutil.which(command)
            if path is not None:
                return path
        return None

    @property
    def available(self) -> bool:
        return self.command is not None

    def start(self, path: str, volume: float) -> subprocess.Popen[bytes] | None:
        if self.command is None:
            return None
        executable = Path(self.command).name
        if executable == "afplay":
            arguments = [self.command, "-v", str(volume), path]
        elif executable == "ffplay":
            arguments = [
                self.command,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(round(volume * 100)),
                path,
            ]
        else:
            arguments = [self.command, path]
        return subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class LocalAudioExperience:
    """Coordinate voice, original ambience, and local host playback."""

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        cache_dir: Path,
        *,
        voice_enabled: bool = True,
        music_enabled: bool = True,
    ) -> None:
        self.synthesizer = synthesizer
        self.cache_dir = cache_dir
        self._voice_enabled = voice_enabled
        self._music_enabled = music_enabled
        self.player = SubprocessAudioPlayer()
        self._shutdown = threading.Event()
        self._speaking = threading.Event()
        self._music_thread: threading.Thread | None = None
        self._music_process: subprocess.Popen[bytes] | None = None
        self._voice_process: subprocess.Popen[bytes] | None = None
        self._process_lock = threading.Lock()
        self._narration_lock = threading.Lock()

    @property
    def voice_enabled(self) -> bool:
        return self._voice_enabled and self.player.available

    @property
    def music_enabled(self) -> bool:
        return self._music_enabled and self.player.available

    def start(self) -> None:
        if self.music_enabled:
            self._ensure_music_thread()

    def narrate(self, text: str, language: LanguageCode) -> None:
        if not self.voice_enabled or self._shutdown.is_set():
            return
        with self._narration_lock:
            if not self.voice_enabled or self._shutdown.is_set():
                return
            try:
                speech = self.synthesizer.synthesize(text, language)
                if self._shutdown.is_set() or not self.voice_enabled:
                    return
                self._speaking.set()
                self._stop_music_process()
                process = self.player.start(speech, 1.0)
                with self._process_lock:
                    self._voice_process = process
                if process is not None:
                    process.wait()
            finally:
                with self._process_lock:
                    self._voice_process = None
                self._speaking.clear()

    def toggle_voice(self) -> bool:
        self._voice_enabled = not self._voice_enabled
        if not self._voice_enabled:
            self._stop_voice_process()
        return self.voice_enabled

    def toggle_music(self) -> bool:
        self._music_enabled = not self._music_enabled
        if self._music_enabled:
            self._ensure_music_thread()
        else:
            self._stop_music_process()
        return self.music_enabled

    def stop(self) -> None:
        self._shutdown.set()
        self._stop_voice_process()
        self._stop_music_process()
        if self._music_thread is not None:
            self._music_thread.join(timeout=1)

    def _ensure_music_thread(self) -> None:
        if self._music_thread is not None and self._music_thread.is_alive():
            return
        self._music_thread = threading.Thread(
            target=self._music_loop,
            name="dungeon-ambience",
            daemon=True,
        )
        self._music_thread.start()

    def _music_loop(self) -> None:
        ambience = str(self._create_ambience())
        while not self._shutdown.is_set():
            if not self.music_enabled or self._speaking.is_set():
                self._shutdown.wait(0.1)
                continue
            process = self.player.start(ambience, 0.16)
            with self._process_lock:
                self._music_process = process
            if process is None:
                return
            process.wait()
            with self._process_lock:
                if self._music_process is process:
                    self._music_process = None

    def _stop_music_process(self) -> None:
        with self._process_lock:
            process = self._music_process
            self._music_process = None
        self._terminate(process)

    def _stop_voice_process(self) -> None:
        with self._process_lock:
            process = self._voice_process
            self._voice_process = None
        self._terminate(process)

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes] | None) -> None:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()

    def _create_ambience(self) -> Path:
        output = self.cache_dir / "original-tavern-ambience.wav"
        if output.is_file():
            return output
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        sample_rate = 22_050
        duration_seconds = 12
        frame_count = sample_rate * duration_seconds
        temporary = output.with_suffix(".tmp")
        with wave.open(str(temporary), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            frames = bytearray()
            notes = (146.83, 174.61, 220.00, 196.00)
            for index in range(frame_count):
                time = index / sample_rate
                note = notes[int(time // 3) % len(notes)]
                drone = 0.28 * math.sin(2 * math.pi * 73.42 * time)
                harmony = 0.16 * math.sin(2 * math.pi * note * time)
                pulse = 0.07 * math.sin(2 * math.pi * (note * 2) * time)
                envelope = 0.72 + 0.28 * math.sin(2 * math.pi * time / duration_seconds)
                value = max(-1.0, min(1.0, (drone + harmony + pulse) * envelope))
                frames.extend(struct.pack("<h", round(value * 32767)))
            audio.writeframes(frames)
        temporary.replace(output)
        return output

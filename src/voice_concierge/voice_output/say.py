"""macOS ``say`` text-to-speech backend.

Useful as a dependency-free fallback on macOS, where the bundled piper wheel
cannot locate its espeak-ng data and therefore produces no audio.
"""

# Standard library
import subprocess
import tempfile
import wave
from pathlib import Path

# Third-party
import numpy as np

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_output.errors import (
    TextToSpeechBackendUnavailableError,
    TextToSpeechSynthesisError,
)

DEFAULT_SAY_EXECUTABLE: str = "say"
DEFAULT_SAMPLE_RATE: int = 22050


class SayTextToSpeech:
    """TextToSpeech backed by the macOS ``say`` command. Synthesis only."""

    def __init__(
        self,
        *,
        voice: str | None = None,
        rate_wpm: int | None = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        executable: str = DEFAULT_SAY_EXECUTABLE,
    ) -> None:
        self._voice = voice
        self._rate_wpm = rate_wpm
        self._sample_rate = sample_rate
        self._executable = executable

    def synthesize(self, text: str) -> CapturedAudio:
        """Run ``say`` to synthesize `text` into an in-memory CapturedAudio."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "say_output.wav"
            self._run_say(text, output_path)
            return self._read_wav(output_path)

    def _run_say(self, text: str, output_path: Path) -> None:
        command = [
            self._executable,
            "-o",
            str(output_path),
            f"--data-format=LEI16@{self._sample_rate}",
            "--file-format=WAVE",
        ]
        if self._voice is not None:
            command += ["-v", self._voice]
        if self._rate_wpm is not None:
            command += ["-r", str(self._rate_wpm)]
        command.append(text)

        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
            )
        except FileNotFoundError as exc:
            raise TextToSpeechBackendUnavailableError(
                f"say executable {self._executable!r} was not found "
                "(the say backend requires macOS)."
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
            raise TextToSpeechSynthesisError(f"say synthesis failed: {detail}") from exc
        if not output_path.exists():
            raise TextToSpeechSynthesisError(
                "say did not produce an output audio file."
            )

    @staticmethod
    def _read_wav(path: Path) -> CapturedAudio:
        # NOTE: mirrors PiperTextToSpeech._read_wav; worth extracting to a shared
        # helper if a third backend is added.
        try:
            with wave.open(str(path), "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_rate = wav_file.getframerate()
                sample_width = wav_file.getsampwidth()
                frames = wav_file.readframes(wav_file.getnframes())
        except (OSError, wave.Error) as exc:
            raise TextToSpeechSynthesisError(
                "say produced an unreadable WAV file."
            ) from exc
        if sample_width != 2:
            raise TextToSpeechSynthesisError(
                f"Expected 16-bit PCM audio from say, got {sample_width * 8}-bit."
            )
        return CapturedAudio(
            samples=np.frombuffer(frames, dtype=np.int16),
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )

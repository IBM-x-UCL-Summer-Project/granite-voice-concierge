"""Piper text-to-speech backend."""

# Standard library
import logging
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

logger = logging.getLogger(__name__)

# Piper defaults tuned for older-adult listeners
DEFAULT_MODEL_PATH: str = "en_GB-alan-medium.onnx"
DEFAULT_CONFIG_PATH: str = "en_GB-alan-medium.onnx.json"
DEFAULT_LENGTH_SCALE: float = 1.2  # >1 slows speech; 1.2 suits older adults
MIN_LENGTH_SCALE: float = 0.5      # fast
MAX_LENGTH_SCALE: float = 2.5      # slow
DEFAULT_PIPER_EXECUTABLE: str = "piper"


class PiperTextToSpeech:
    """TextToSpeech backed by the Piper CLI. Synthesis only; playback is separate."""

    @property
    def length_scale(self) -> float:
        return self._length_scale

    @length_scale.setter
    def length_scale(self, value: float) -> None:
        self._length_scale = max(MIN_LENGTH_SCALE, min(MAX_LENGTH_SCALE, float(value)))


    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        config_path: str = DEFAULT_CONFIG_PATH,
        *,
        length_scale: float = DEFAULT_LENGTH_SCALE,
        executable: str = DEFAULT_PIPER_EXECUTABLE,
    ) -> None:
        self._model_path = model_path
        self._config_path = config_path
        self.length_scale = length_scale
        self._executable = executable

    def synthesize(self, text: str, pace_override: float | None = None) -> CapturedAudio:
        """Run Piper to synthesize `text` into an in-memory CapturedAudio."""

        if pace_override is not None:
            self.length_scale = pace_override

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "piper_output.wav"
            self._run_piper(text, output_path)
            return self._read_wav(output_path)

    def _run_piper(self, text: str, output_path: Path) -> None:
        command = [
            self._executable,
            "-m",
            self._model_path,
            "-c",
            self._config_path,
            "-f",
            str(output_path),
            "--length_scale",
            str(self._length_scale),
        ]
        try:
            subprocess.run(
                command,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
            )
        except FileNotFoundError as exc:
            raise TextToSpeechBackendUnavailableError(
                f"Piper executable {self._executable!r} was not found."
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
            raise TextToSpeechSynthesisError(
                f"Piper synthesis failed: {detail}"
            ) from exc
        if not output_path.exists():
            raise TextToSpeechSynthesisError(
                "Piper did not produce an output audio file."
            )

    @staticmethod
    def _read_wav(path: Path) -> CapturedAudio:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(wav_file.getnframes())
        if sample_width != 2:
            raise TextToSpeechSynthesisError(
                f"Expected 16-bit PCM audio from Piper, got {sample_width * 8}-bit."
            )
        return CapturedAudio(
            samples=np.frombuffer(frames, dtype=np.int16),
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )

# Standard library
from collections.abc import Callable
from pathlib import Path

# Third-party
import numpy as np
import openwakeword
import openwakeword.utils
from openwakeword.model import Model

# Local
from voice_concierge.audio import AudioSource, PyAudioSource
from voice_concierge.audio.source import DEFAULT_FORMAT

# Wake word detection constants
DEFAULT_CHUNK: int = 1280  # ~80ms at 16kHz (openWakeWord's expected chunk size)
DEFAULT_RATE: int = 16000  # sample rate required by openWakeWord
DEFAULT_CHANNELS: int = 1  # mono audio
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.3  # from spike benchmarks


def _resolve_model_reference(model_name: str) -> str:
    """Return a model path when bundled resources are present, else the name."""
    model_path = Path(model_name)
    if model_path.is_file():
        return str(model_path)

    bundled_model_path = (
        Path(openwakeword.__file__).resolve().parent
        / "resources"
        / "models"
        / model_name
    )
    if bundled_model_path.is_file():
        return str(bundled_model_path)

    return model_name


class WakeWordDetector:
    """
    Detects a wake word from live microphone input using openWakeWord.

    Listens continuously to the audio source and calls the provided callback
    when the wake word confidence exceeds the threshold. Resets automatically
    after each detection to allow successive triggers.

    Usage:
        detector = WakeWordDetector()
        detector.listen(on_wake_word=my_callback)
    """

    def __init__(
        self,
        model_name: str = "hey_jarvis_v0.1.onnx",
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        chunk: int = DEFAULT_CHUNK,
        rate: int = DEFAULT_RATE,
        channels: int = DEFAULT_CHANNELS,
        fmt: int = DEFAULT_FORMAT,
        download_models: bool = True,
        audio_source: AudioSource | None = None,
    ) -> None:
        """
        Initialise the wake word detector.

        Args:
            model_name: filename of the openWakeWord ONNX model to load.
            confidence_threshold: minimum confidence score to trigger detection.
            chunk: number of audio samples per chunk.
            rate: audio sample rate in Hz.
            channels: number of audio channels.
            fmt: PyAudio format constant.
            download_models: whether to fetch bundled openWakeWord models.
            audio_source: microphone source to read from. If None, a default
                PyAudioSource is created.
        """
        self._confidence_threshold = confidence_threshold
        self._chunk = chunk
        self._rate = rate
        self._channels = channels
        self._fmt = fmt
        self._audio_source: AudioSource = audio_source or PyAudioSource(
            rate=rate, channels=channels, fmt=fmt, frames_per_buffer=chunk
        )

        if download_models and hasattr(openwakeword.utils, "download_models"):
            openwakeword.utils.download_models()

        model_reference = _resolve_model_reference(model_name)
        try:
            self._model: Model = Model(
                wakeword_models=[model_reference],
                inference_framework="onnx",
            )
        except TypeError as exc:
            if "wakeword_models" not in str(exc):
                raise
            self._model = Model(wakeword_model_paths=[model_reference])

    def listen(self, on_wake_word: Callable[[], None]) -> None:
        """
        Start listening for the wake word continuously.

        Blocks until KeyboardInterrupt. Calls on_wake_word() each time
        the wake word is detected and resets the model buffer.

        Args:
            on_wake_word: callback to invoke on wake word detection.
        """
        self._audio_source.open()
        print("Wake word detector listening...")

        try:
            while True:
                audio_chunk: bytes = self._audio_source.read(self._chunk)
                audio_np: np.ndarray = np.frombuffer(audio_chunk, dtype=np.int16)

                self._model.predict(audio_np)

                for wake_word, confidence in self._model.prediction_buffer.items():
                    if confidence[-1] > self._confidence_threshold:
                        print(
                            f"Wake word detected: '{wake_word}' "
                            f"(confidence: {confidence[-1]:.2f})"
                        )
                        self._model.reset()

                        # Close the mic before invoking the callback so the VAD
                        # can open the same device.
                        self._audio_source.close()
                        on_wake_word()
                        return

        except KeyboardInterrupt:
            print("\nWake word detector stopped.")
            raise
        finally:
            self._audio_source.close()

# Standard library
from typing import Callable

# Third-party
import numpy as np
import openwakeword.utils
import pyaudio
from openwakeword.model import Model

# Wake word detection constants
DEFAULT_CHUNK: int = 1280  # ~80ms at 16kHz (openWakeWord's expected chunk size)
DEFAULT_RATE: int = 16000  # sample rate required by openWakeWord
DEFAULT_CHANNELS: int = 1  # mono audio
DEFAULT_FORMAT: int = pyaudio.paInt16
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.3  # from spike benchmarks


class WakeWordDetector:
    """
    Detects a wake word from live microphone input using openWakeWord.

    Listens continuously to the microphone and calls the provided callback
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
        """
        self._confidence_threshold = confidence_threshold
        self._chunk = chunk
        self._rate = rate
        self._channels = channels
        self._fmt = fmt

        # Download pre-trained models on first run
        openwakeword.utils.download_models()

        self._model: Model = Model(
            wakeword_models=[model_name],
            inference_framework="onnx",
        )

    def listen(self, on_wake_word: Callable[[], None]) -> None:
        """
        Start listening for the wake word continuously.

        Blocks until KeyboardInterrupt. Calls on_wake_word() each time
        the wake word is detected and resets the model buffer.

        Args:
            on_wake_word: callback to invoke on wake word detection.
        """
        p: pyaudio.PyAudio = pyaudio.PyAudio()
        stream: pyaudio.Stream = p.open(
            format=self._fmt,
            channels=self._channels,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )

        print("Wake word detector listening...")

        try:
            while True:
                audio_chunk: bytes = stream.read(
                    self._chunk, exception_on_overflow=False
                )
                audio_np: np.ndarray = np.frombuffer(audio_chunk, dtype=np.int16)

                self._model.predict(audio_np)

                for wake_word, confidence in self._model.prediction_buffer.items():
                    if confidence[-1] > self._confidence_threshold:
                        print(
                            f"Wake word detected: '{wake_word}' "
                            f"(confidence: {confidence[-1]:.2f})"
                        )
                        self._model.reset()

                        # Close stream before invoking callback to free microphone
                        # for VAD to open on the same device
                        stream.stop_stream()
                        stream.close()
                        p.terminate()

                        on_wake_word()
                        return

        except KeyboardInterrupt:
            print("\nWake word detector stopped.")
            raise
        finally:
            try:
                stream.stop_stream()
                stream.close()
                p.terminate()
            except Exception:
                pass

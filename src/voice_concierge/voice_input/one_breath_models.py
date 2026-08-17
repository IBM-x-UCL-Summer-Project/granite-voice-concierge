"""Adapters that put the real recognisers behind the chunk-level protocols.

Everything here is a thin shim over a native model, and none of it can run
without loading that model, so it is excluded from coverage. The logic worth
testing lives in `one_breath`, which is why these adapters exist at all: they
reduce openWakeWord and Silero to a single question each, so the module that
decides what to do with the answers can be tested with no model present.
"""

# Standard library
from typing import Final

# Third-party
import numpy as np
import torch
from silero_vad import VADIterator, load_silero_vad

# Local
from voice_concierge.voice_input.one_breath import SpeechVerdict
from voice_concierge.voice_input.wake_word_detector import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    _resolve_model_reference,
)

#: The wake word the app ships with.
DEFAULT_MODEL_NAME: Final[str] = "hey_jarvis_v0.1.onnx"

#: Silero's own default speech threshold.
DEFAULT_SPEECH_THRESHOLD: Final[float] = 0.5

#: Silence before an utterance counts as finished.
DEFAULT_MIN_SILENCE_MS: Final[int] = 500

#: Padding kept either side of detected speech.
DEFAULT_PADDING_MS: Final[int] = 100

#: Full scale of a 16-bit sample, for normalising to the [-1, 1] Silero wants.
_INT16_FULL_SCALE: Final[float] = 32768.0


class OpenWakeWordSpotter:  # pragma: no cover - wraps a native ONNX model
    """Answers whether a chunk completed the wake word."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        download_models: bool = False,
    ) -> None:
        import openwakeword.utils
        from openwakeword.model import Model

        if download_models:
            openwakeword.utils.download_models()

        self._threshold = confidence_threshold
        self._model = Model(wakeword_models=[_resolve_model_reference(model_name)])

    def spotted(self, chunk: bytes) -> bool:
        """True when any loaded wake word crosses the confidence threshold."""
        if not chunk:
            return False

        self._model.predict(np.frombuffer(chunk, dtype=np.int16))
        return any(
            scores[-1] > self._threshold
            for scores in self._model.prediction_buffer.values()
            if len(scores)
        )

    def reset(self) -> None:
        """Clear the model's rolling audio, so scores do not carry over."""
        self._model.reset()


class SileroSpeechGate:  # pragma: no cover - wraps a native torch model
    """Reports where speech starts and stops within a stream of chunks."""

    def __init__(
        self,
        *,
        rate: int = 16000,
        threshold: float = DEFAULT_SPEECH_THRESHOLD,
        min_silence_ms: int = DEFAULT_MIN_SILENCE_MS,
        padding_ms: int = DEFAULT_PADDING_MS,
    ) -> None:
        self._rate = rate
        self._threshold = threshold
        self._min_silence_ms = min_silence_ms
        self._padding_ms = padding_ms
        self._model = load_silero_vad()
        self._iterator = self._build_iterator()

    def _build_iterator(self) -> VADIterator:
        return VADIterator(
            self._model,
            threshold=self._threshold,
            sampling_rate=self._rate,
            min_silence_duration_ms=self._min_silence_ms,
            speech_pad_ms=self._padding_ms,
        )

    def classify(self, chunk: bytes) -> SpeechVerdict | None:
        """Return "start" or "end" at a boundary, otherwise None."""
        if not chunk:
            return None

        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32, copy=False)
        verdict = self._iterator(
            torch.from_numpy(samples).div(_INT16_FULL_SCALE),
            return_seconds=False,
        )
        if verdict is None:
            return None
        if "start" in verdict:
            return "start"
        if "end" in verdict:
            return "end"
        return None

    def reset(self) -> None:
        """Drop the iterator's internal state between utterances."""
        self._iterator.reset_states()

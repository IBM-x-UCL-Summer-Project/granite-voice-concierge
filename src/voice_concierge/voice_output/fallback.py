"""Ordered fallback composition for text-to-speech backends."""

# Standard library
import logging

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_output.errors import (
    TextToSpeechError,
    TextToSpeechSynthesisError,
)
from voice_concierge.voice_output.interfaces import TextToSpeech

logger = logging.getLogger(__name__)


class FallbackTextToSpeech:
    """Try local text-to-speech backends in priority order."""

    def __init__(self, *backends: TextToSpeech) -> None:
        if not backends:
            raise ValueError("At least one text-to-speech backend is required.")
        self._backends = backends

    def synthesize(self, text: str) -> CapturedAudio:
        """Return audio from the first backend that synthesizes successfully."""
        last_error: TextToSpeechError | None = None
        for backend in self._backends:
            try:
                audio = backend.synthesize(text)
                if audio.samples.size == 0 or not audio.samples.any():
                    raise TextToSpeechSynthesisError(
                        f"{type(backend).__name__} produced silent audio."
                    )
                return audio
            except TextToSpeechError as exc:
                last_error = exc
                logger.warning(
                    "Text-to-speech backend %s failed: %s",
                    type(backend).__name__,
                    exc,
                )

        if last_error is None:  # pragma: no cover - guarded by __init__
            raise RuntimeError("No text-to-speech backend was attempted.")
        raise last_error

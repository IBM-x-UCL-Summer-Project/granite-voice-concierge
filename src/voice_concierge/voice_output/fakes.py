"""Deterministic text-to-speech fake for tests and wiring."""

# Third-party
import numpy as np

# Local
from voice_concierge.audio import CapturedAudio


class DeterministicTextToSpeechFake:
    """Configurable TextToSpeech fake that records the text it receives."""

    def __init__(self, audio: CapturedAudio | None = None) -> None:
        self.audio = (
            audio
            if audio is not None
            else CapturedAudio(samples=np.zeros(16000, dtype=np.int16))
        )
        self.calls: list[str] = []

    def synthesize(self, text: str) -> CapturedAudio:
        """Record the text and return the configured audio unchanged."""
        self.calls.append(text)
        return self.audio

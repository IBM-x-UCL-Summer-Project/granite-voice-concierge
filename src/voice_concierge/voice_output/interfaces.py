"""Text-to-speech interface consumed by the voice pipeline."""

# Standard library
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.audio import CapturedAudio


@runtime_checkable
class TextToSpeech(Protocol):
    """Synthesize spoken audio from text."""

    def synthesize(self, text: str) -> CapturedAudio:
        """Return synthesized speech audio for the given text (no playback)."""

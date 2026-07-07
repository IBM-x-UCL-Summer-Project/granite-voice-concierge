"""Speech-to-text interface consumed by the voice pipeline."""

# Standard library
from typing import Protocol, runtime_checkable

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_input.stt.types import Transcript


@runtime_checkable
class SpeechToText(Protocol):
    """Transcribe a captured utterance into text."""

    def transcribe(self, audio: CapturedAudio) -> Transcript:
        """Return the transcript for the given captured audio."""

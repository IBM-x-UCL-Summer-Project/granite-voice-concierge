"""Deterministic speech-to-text fake for tests and wiring."""

# Local
from voice_concierge.audio import CapturedAudio
from voice_concierge.voice_input.stt.types import Transcript


class DeterministicSpeechToTextFake:
    """Configurable SpeechToText fake that records the audio it receives."""

    def __init__(self, transcript: Transcript | None = None) -> None:
        self.transcript = (
            transcript
            if transcript is not None
            else Transcript(text="deterministic transcript")
        )
        self.calls: list[CapturedAudio] = []

    def transcribe(self, audio: CapturedAudio) -> Transcript:
        """Record the audio and return the configured transcript unchanged."""
        self.calls.append(audio)
        return self.transcript

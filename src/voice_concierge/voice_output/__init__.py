"""Text-to-speech interfaces and backends for the voice pipeline."""

from voice_concierge.voice_output.fakes import DeterministicTextToSpeechFake
from voice_concierge.voice_output.interfaces import TextToSpeech

__all__ = [
    "DeterministicTextToSpeechFake",
    "TextToSpeech",
]

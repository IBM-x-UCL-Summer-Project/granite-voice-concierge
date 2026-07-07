"""Speech-to-text interfaces and backends for the voice pipeline."""

from voice_concierge.voice_input.stt.fakes import DeterministicSpeechToTextFake
from voice_concierge.voice_input.stt.interfaces import SpeechToText
from voice_concierge.voice_input.stt.types import Transcript

__all__ = [
    "DeterministicSpeechToTextFake",
    "SpeechToText",
    "Transcript",
]

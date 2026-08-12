"""Text-to-speech interfaces and backends for the voice pipeline."""

from voice_concierge.voice_output.errors import (
    TextToSpeechBackendUnavailableError,
    TextToSpeechError,
    TextToSpeechSynthesisError,
)
from voice_concierge.voice_output.factory import build_text_to_speech
from voice_concierge.voice_output.fakes import DeterministicTextToSpeechFake
from voice_concierge.voice_output.interfaces import TextToSpeech
from voice_concierge.voice_output.pacing import (
    DEFAULT_PACE_LEVEL,
    PACE_LADDER,
    PacedTextToSpeech,
    SpeechRate,
    acknowledgement,
)
from voice_concierge.voice_output.piper import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_LENGTH_SCALE,
    DEFAULT_MODEL_PATH,
    DEFAULT_PIPER_EXECUTABLE,
    PiperTextToSpeech,
)
from voice_concierge.voice_output.say import (
    DEFAULT_SAY_EXECUTABLE,
    SayTextToSpeech,
)

__all__ = [
    "DEFAULT_PACE_LEVEL",
    "PACE_LADDER",
    "PacedTextToSpeech",
    "SpeechRate",
    "acknowledgement",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_LENGTH_SCALE",
    "DEFAULT_MODEL_PATH",
    "DEFAULT_PIPER_EXECUTABLE",
    "DEFAULT_SAY_EXECUTABLE",
    "DeterministicTextToSpeechFake",
    "PiperTextToSpeech",
    "SayTextToSpeech",
    "TextToSpeech",
    "TextToSpeechBackendUnavailableError",
    "TextToSpeechError",
    "TextToSpeechSynthesisError",
    "build_text_to_speech",
]

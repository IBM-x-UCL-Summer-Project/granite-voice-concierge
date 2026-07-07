"""Text-to-speech interfaces and backends for the voice pipeline."""

from voice_concierge.voice_output.errors import (
    TextToSpeechBackendUnavailableError,
    TextToSpeechError,
    TextToSpeechSynthesisError,
)
from voice_concierge.voice_output.fakes import DeterministicTextToSpeechFake
from voice_concierge.voice_output.interfaces import TextToSpeech
from voice_concierge.voice_output.piper import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_LENGTH_SCALE,
    DEFAULT_MODEL_PATH,
    DEFAULT_PIPER_EXECUTABLE,
    PiperTextToSpeech,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_LENGTH_SCALE",
    "DEFAULT_MODEL_PATH",
    "DEFAULT_PIPER_EXECUTABLE",
    "DeterministicTextToSpeechFake",
    "PiperTextToSpeech",
    "TextToSpeech",
    "TextToSpeechBackendUnavailableError",
    "TextToSpeechError",
    "TextToSpeechSynthesisError",
]

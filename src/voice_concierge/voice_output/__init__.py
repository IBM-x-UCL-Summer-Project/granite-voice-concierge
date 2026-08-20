"""Text-to-speech interfaces and backends for the voice pipeline."""

from voice_concierge.voice_output.errors import (
    TextToSpeechBackendUnavailableError,
    TextToSpeechError,
    TextToSpeechSynthesisError,
)
from voice_concierge.voice_output.factory import build_text_to_speech
from voice_concierge.voice_output.fakes import DeterministicTextToSpeechFake
from voice_concierge.voice_output.fallback import FallbackTextToSpeech
from voice_concierge.voice_output.interfaces import TextToSpeech
from voice_concierge.voice_output.pace_store import (
    DEFAULT_PACE_PATH,
    load_rate,
    save_rate,
)
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
    DEFAULT_MODEL_DIRECTORY,
    DEFAULT_MODEL_PATH,
    DEFAULT_PIPER_EXECUTABLE,
    DEFAULT_VOICE,
    PiperTextToSpeech,
    resolve_piper_voice_paths,
)
from voice_concierge.voice_output.say import (
    DEFAULT_SAY_EXECUTABLE,
    SayTextToSpeech,
)

__all__ = [
    "DEFAULT_PACE_PATH",
    "load_rate",
    "save_rate",
    "DEFAULT_PACE_LEVEL",
    "PACE_LADDER",
    "PacedTextToSpeech",
    "SpeechRate",
    "acknowledgement",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_LENGTH_SCALE",
    "DEFAULT_MODEL_DIRECTORY",
    "DEFAULT_MODEL_PATH",
    "DEFAULT_PIPER_EXECUTABLE",
    "DEFAULT_SAY_EXECUTABLE",
    "DEFAULT_VOICE",
    "DeterministicTextToSpeechFake",
    "FallbackTextToSpeech",
    "PiperTextToSpeech",
    "SayTextToSpeech",
    "TextToSpeech",
    "TextToSpeechBackendUnavailableError",
    "TextToSpeechError",
    "TextToSpeechSynthesisError",
    "build_text_to_speech",
    "resolve_piper_voice_paths",
]

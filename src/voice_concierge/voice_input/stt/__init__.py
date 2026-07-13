"""Speech-to-text interfaces and backends for the voice pipeline."""

from voice_concierge.voice_input.stt.errors import (
    SpeechToTextBackendUnavailableError,
    SpeechToTextError,
    SpeechToTextTranscriptionError,
)
from voice_concierge.voice_input.stt.factory import build_speech_to_text
from voice_concierge.voice_input.stt.fakes import DeterministicSpeechToTextFake
from voice_concierge.voice_input.stt.interfaces import SpeechToText
from voice_concierge.voice_input.stt.types import Transcript
from voice_concierge.voice_input.stt.whisper import (
    DEFAULT_BEAM_SIZE,
    DEFAULT_COMPUTE_TYPE,
    DEFAULT_DEVICE,
    DEFAULT_MODEL_SIZE,
    DEFAULT_VAD_FILTER,
    WhisperSpeechToText,
)

__all__ = [
    "DEFAULT_BEAM_SIZE",
    "DEFAULT_COMPUTE_TYPE",
    "DEFAULT_DEVICE",
    "DEFAULT_MODEL_SIZE",
    "DEFAULT_VAD_FILTER",
    "DeterministicSpeechToTextFake",
    "SpeechToText",
    "build_speech_to_text",
    "SpeechToTextBackendUnavailableError",
    "SpeechToTextError",
    "SpeechToTextTranscriptionError",
    "Transcript",
    "WhisperSpeechToText",
]

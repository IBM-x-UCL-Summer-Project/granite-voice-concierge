"""Construction helpers for speech-to-text backends."""

# Local
from voice_concierge.voice_input.stt.interfaces import SpeechToText
from voice_concierge.voice_input.stt.whisper import (
    DEFAULT_COMPUTE_TYPE,
    DEFAULT_DEVICE,
    DEFAULT_MODEL_SIZE,
    WhisperSpeechToText,
)


def build_speech_to_text(
    model_size: str = DEFAULT_MODEL_SIZE,
    *,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
) -> SpeechToText:
    """Build the default local speech-to-text engine for application code."""
    return WhisperSpeechToText(model_size, device=device, compute_type=compute_type)

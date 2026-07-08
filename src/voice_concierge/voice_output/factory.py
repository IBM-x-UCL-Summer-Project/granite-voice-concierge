"""Construction helpers for text-to-speech backends."""

# Local
from voice_concierge.voice_output.interfaces import TextToSpeech
from voice_concierge.voice_output.piper import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_LENGTH_SCALE,
    DEFAULT_MODEL_PATH,
    PiperTextToSpeech,
)


def build_text_to_speech(
    model_path: str = DEFAULT_MODEL_PATH,
    config_path: str = DEFAULT_CONFIG_PATH,
    *,
    length_scale: float = DEFAULT_LENGTH_SCALE,
) -> TextToSpeech:
    """Build the default local text-to-speech engine for application code."""
    return PiperTextToSpeech(model_path, config_path, length_scale=length_scale)

"""Typed configuration for the application's local speech backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from voice_concierge.voice_input.stt.interfaces import SpeechToText
from voice_concierge.voice_input.stt.whisper import (
    DEFAULT_COMPUTE_TYPE,
    DEFAULT_DEVICE,
    DEFAULT_MODEL_SIZE,
)
from voice_concierge.voice_output.interfaces import TextToSpeech
from voice_concierge.voice_output.piper import (
    DEFAULT_MODEL_DIRECTORY,
    DEFAULT_VOICE,
    resolve_piper_voice_paths,
)


@dataclass(frozen=True)
class VoiceIOConfig:
    """Model selections shared by the browser and live voice entry points."""

    stt_model: str = DEFAULT_MODEL_SIZE
    stt_device: str = DEFAULT_DEVICE
    stt_compute_type: str = DEFAULT_COMPUTE_TYPE
    tts_voice: str = DEFAULT_VOICE
    tts_model_directory: Path | str = DEFAULT_MODEL_DIRECTORY

    def __post_init__(self) -> None:
        for field_name in ("stt_model", "stt_device", "stt_compute_type"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must not be empty.")
        # Resolve once for validation. The model files may be downloaded later,
        # so configuration validation deliberately does not require them yet.
        resolve_piper_voice_paths(self.tts_voice, self.tts_model_directory)


def build_configured_speech_to_text(config: VoiceIOConfig) -> SpeechToText:
    """Build faster-whisper from application-level voice configuration."""

    from voice_concierge.voice_input.stt.factory import build_speech_to_text

    return build_speech_to_text(
        config.stt_model,
        device=config.stt_device,
        compute_type=config.stt_compute_type,
    )


def build_configured_text_to_speech(config: VoiceIOConfig) -> TextToSpeech:
    """Build the configured local Piper voice and existing fallbacks."""

    from voice_concierge.voice_output.factory import build_text_to_speech

    return build_text_to_speech(
        voice=config.tts_voice,
        model_directory=config.tts_model_directory,
    )

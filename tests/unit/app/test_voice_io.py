"""Tests for application-level voice backend configuration."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from voice_concierge.app.voice_io import (
    VoiceIOConfig,
    build_configured_speech_to_text,
    build_configured_text_to_speech,
)


def test_voice_io_defaults_preserve_existing_backends() -> None:
    config = VoiceIOConfig()

    assert config.stt_model == "base.en"
    assert config.stt_device == "cpu"
    assert config.stt_compute_type == "int8"
    assert config.tts_voice == "en_GB-alan-medium"


@pytest.mark.parametrize("field_name", ("stt_model", "stt_device", "stt_compute_type"))
def test_voice_io_rejects_empty_stt_configuration(field_name: str) -> None:
    values = {
        "stt_model": "base.en",
        "stt_device": "cpu",
        "stt_compute_type": "int8",
    }
    values[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        VoiceIOConfig(**values)


@patch("voice_concierge.voice_input.stt.factory.build_speech_to_text")
def test_builds_selected_whisper_configuration(mock_build: Mock) -> None:
    config = VoiceIOConfig(
        stt_model="large-v3-turbo",
        stt_device="cuda",
        stt_compute_type="float16",
    )

    result = build_configured_speech_to_text(config)

    mock_build.assert_called_once_with(
        "large-v3-turbo",
        device="cuda",
        compute_type="float16",
    )
    assert result is mock_build.return_value


@patch("voice_concierge.voice_output.factory.build_text_to_speech")
def test_builds_selected_piper_voice(mock_build: Mock, tmp_path: Path) -> None:
    config = VoiceIOConfig(
        tts_voice="en_US-lessac-medium",
        tts_model_directory=tmp_path,
    )

    result = build_configured_text_to_speech(config)

    mock_build.assert_called_once_with(
        voice="en_US-lessac-medium",
        model_directory=tmp_path,
    )
    assert result is mock_build.return_value

# Standard library
from unittest.mock import patch

# Third-party
import pytest

# Local
from voice_concierge.voice_input.stt import build_speech_to_text


class TestBuildSpeechToText:
    """Unit tests for the build_speech_to_text factory."""

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.stt.factory.WhisperSpeechToText")
    def test_builds_with_defaults(self, mock_whisper: patch) -> None:
        """The factory builds a WhisperSpeechToText with default config."""
        engine = build_speech_to_text()

        mock_whisper.assert_called_once_with(
            "base.en", device="cpu", compute_type="int8"
        )
        assert engine is mock_whisper.return_value

    @pytest.mark.unit
    @patch("voice_concierge.voice_input.stt.factory.WhisperSpeechToText")
    def test_forwards_custom_config(self, mock_whisper: patch) -> None:
        """The factory forwards a custom model size, device and compute type."""
        build_speech_to_text(
            "small.en", device="cuda", compute_type="float16"
        )

        mock_whisper.assert_called_once_with(
            "small.en", device="cuda", compute_type="float16"
        )

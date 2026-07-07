# Standard library
from unittest.mock import patch

# Third-party
import pytest

# Local
from voice_concierge.voice_output import build_text_to_speech


class TestBuildTextToSpeech:
    """Unit tests for the build_text_to_speech factory."""

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.factory.PiperTextToSpeech")
    def test_builds_with_defaults(self, mock_piper: patch) -> None:
        """The factory builds a PiperTextToSpeech with default config."""
        engine = build_text_to_speech()

        mock_piper.assert_called_once_with(
            "en_GB-alan-medium.onnx",
            "en_GB-alan-medium.onnx.json",
            length_scale=1.2,
        )
        assert engine is mock_piper.return_value

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.factory.PiperTextToSpeech")
    def test_forwards_custom_config(self, mock_piper: patch) -> None:
        """The factory forwards a custom model, config and length scale."""
        build_text_to_speech("voice.onnx", "voice.json", length_scale=1.5)

        mock_piper.assert_called_once_with(
            "voice.onnx", "voice.json", length_scale=1.5
        )

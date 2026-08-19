# Standard library
from unittest.mock import patch

# Third-party
import pytest

# Local
from voice_concierge.voice_output import build_text_to_speech
from voice_concierge.voice_output.piper import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_LENGTH_SCALE,
    DEFAULT_MODEL_PATH,
)


class TestBuildTextToSpeech:
    """Unit tests for the build_text_to_speech factory."""

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.factory.PiperTextToSpeech")
    def test_builds_with_defaults(self, mock_piper: patch) -> None:
        """The factory builds a PiperTextToSpeech with default config."""
        engine = build_text_to_speech(allow_fallback=False)

        mock_piper.assert_called_once_with(
            DEFAULT_MODEL_PATH,
            DEFAULT_CONFIG_PATH,
            length_scale=DEFAULT_LENGTH_SCALE,
        )
        assert engine is mock_piper.return_value

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.factory.PiperTextToSpeech")
    def test_the_default_voice_can_survive_a_broken_piper(
        self, mock_piper: patch
    ) -> None:
        """Piper raises on macOS arm64; the app must still speak (issue #52)."""
        mock_piper.return_value.synthesize.side_effect = RuntimeError("no espeak")

        engine = build_text_to_speech()

        assert engine.synthesize("hello") is not None
        assert engine.using_fallback is True

    @pytest.mark.unit
    @patch("voice_concierge.voice_output.factory.PiperTextToSpeech")
    def test_forwards_custom_config(self, mock_piper: patch) -> None:
        """The factory forwards a custom model, config and length scale."""
        build_text_to_speech(
            "voice.onnx", "voice.json", length_scale=1.5, allow_fallback=False
        )

        mock_piper.assert_called_once_with("voice.onnx", "voice.json", length_scale=1.5)

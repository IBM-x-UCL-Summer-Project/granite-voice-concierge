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
    @patch(
        "voice_concierge.voice_output.factory._find_macos_say_executable",
        return_value=None,
    )
    @patch("voice_concierge.voice_output.factory.FallbackTextToSpeech")
    @patch("voice_concierge.voice_output.factory.PiperTextToSpeech")
    def test_builds_with_defaults(
        self,
        mock_piper: patch,
        mock_fallback: patch,
        _mock_find_say: patch,
    ) -> None:
        """The factory validates Piper output even without another backend."""
        engine = build_text_to_speech()

        mock_piper.assert_called_once_with(
            DEFAULT_MODEL_PATH,
            DEFAULT_CONFIG_PATH,
            length_scale=DEFAULT_LENGTH_SCALE,
        )
        mock_fallback.assert_called_once_with(mock_piper.return_value)
        assert engine is mock_fallback.return_value

    @pytest.mark.unit
    @patch(
        "voice_concierge.voice_output.factory._find_macos_say_executable",
        return_value=None,
    )
    @patch("voice_concierge.voice_output.factory.FallbackTextToSpeech")
    @patch("voice_concierge.voice_output.factory.PiperTextToSpeech")
    def test_forwards_custom_config(
        self,
        mock_piper: patch,
        mock_fallback: patch,
        _mock_find_say: patch,
    ) -> None:
        """The factory forwards a custom model, config and length scale."""
        build_text_to_speech("voice.onnx", "voice.json", length_scale=1.5)

        mock_piper.assert_called_once_with("voice.onnx", "voice.json", length_scale=1.5)
        mock_fallback.assert_called_once_with(mock_piper.return_value)

    @pytest.mark.unit
    @patch(
        "voice_concierge.voice_output.factory._find_macos_say_executable",
        return_value="/usr/bin/say",
    )
    @patch("voice_concierge.voice_output.factory.FallbackTextToSpeech")
    @patch("voice_concierge.voice_output.factory.SayTextToSpeech")
    @patch("voice_concierge.voice_output.factory.PiperTextToSpeech")
    def test_adds_macos_say_as_fallback(
        self,
        mock_piper: patch,
        mock_say: patch,
        mock_fallback: patch,
        _mock_find_say: patch,
    ) -> None:
        """The native macOS voice follows Piper when it is available."""
        engine = build_text_to_speech()

        mock_say.assert_called_once_with(executable="/usr/bin/say")
        mock_fallback.assert_called_once_with(
            mock_piper.return_value,
            mock_say.return_value,
        )
        assert engine is mock_fallback.return_value
